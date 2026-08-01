import asyncio
import logging
import os
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.core.docker_client import get_docker_client
from app.models.database import Instance, InstanceMetrics, ServerMetrics

logger = logging.getLogger(__name__)

_collector_task = None


async def _collect_instance_metrics():
    """Collect metrics from all running MT5 Docker containers and persist them."""
    try:
        client = get_docker_client()
    except Exception as e:
        logger.warning(f"Could not connect to Docker daemon: {e}")
        return

    containers = await asyncio.to_thread(
        client.containers.list, filters={"label": "mt5-router.instance"}
    )

    if not containers:
        return

    db = SessionLocal()
    try:
        for container in containers:
            if container.status != "running":
                continue
            try:
                stats = await asyncio.to_thread(container.stats, stream=False)

                cpu_delta = (
                    stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - stats["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                system_delta = (
                    stats["cpu_stats"]["system_cpu_usage"]
                    - stats["precpu_stats"]["system_cpu_usage"]
                )
                cpu_percent = max(0.0, cpu_delta / system_delta * 100.0) if system_delta > 0 else 0

                memory_usage = stats["memory_stats"].get("usage", 0)
                memory_limit = stats["memory_stats"].get("limit", 1)
                memory_percent = (
                    (memory_usage / memory_limit * 100.0) if memory_limit > 0 else 0
                )

                # Network stats
                networks = stats.get("networks", {})
                rx_bytes = sum(
                    net.get("rx_bytes", 0) for net in networks.values()
                )
                tx_bytes = sum(
                    net.get("tx_bytes", 0) for net in networks.values()
                )

                # Resolve the DB instance by full container id so persisted
                # metrics key off the same instance id the API uses.
                instance = (
                    db.query(Instance)
                    .filter(Instance.docker_container_id == container.id)
                    .first()
                )
                instance_id = instance.id if instance else container.id[:12]
                instance_name = instance.name if instance else container.name

                metric = InstanceMetrics(
                    instance_id=instance_id,
                    instance_name=instance_name,
                    cpu_percent=round(cpu_percent, 2),
                    memory_usage_mb=round(memory_usage / 1024 / 1024, 2),
                    memory_limit_mb=round(memory_limit / 1024 / 1024, 2),
                    memory_percent=round(memory_percent, 2),
                    network_rx_mb=round(rx_bytes / 1024 / 1024, 2),
                    network_tx_mb=round(tx_bytes / 1024 / 1024, 2),
                    recorded_at=datetime.utcnow(),
                )
                db.add(metric)

            except Exception as e:
                logger.error(
                    f"Error collecting metrics for container {container.name}: {e}"
                )

        db.commit()
    except Exception as e:
        logger.error(f"Error persisting instance metrics: {e}")
        db.rollback()
    finally:
        db.close()


async def _cleanup_old_metrics(retention_days: int = 7):
    """Delete metrics records older than the retention period."""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    db = SessionLocal()
    try:
        deleted_instances = (
            db.query(InstanceMetrics)
            .filter(InstanceMetrics.recorded_at < cutoff)
            .delete()
        )
        deleted_servers = (
            db.query(ServerMetrics)
            .filter(ServerMetrics.recorded_at < cutoff)
            .delete()
        )
        db.commit()
        if deleted_instances or deleted_servers:
            logger.info(
                f"Cleaned up old metrics: {deleted_instances} instance records, "
                f"{deleted_servers} server records"
            )
    except Exception as e:
        logger.error(f"Error cleaning up old metrics: {e}")
        db.rollback()
    finally:
        db.close()


async def _metrics_loop(interval: int):
    """Main loop that collects metrics and cleans up old records periodically."""
    logger.info(
        f"Metrics collector started (interval={interval}s, retention=7 days)"
    )
    while True:
        try:
            await _collect_instance_metrics()
            await _cleanup_old_metrics()
        except Exception as e:
            logger.error(f"Unexpected error in metrics collector: {e}")

        await asyncio.sleep(interval)


def start_metrics_collector(interval: int = 60):
    """Start the background metrics collector task.

    Only the ``worker`` process role runs the collector; other roles (e.g.
    the API server) skip it so each process does not collect duplicate data.

    Args:
        interval: Collection interval in seconds (default 60).

    Returns:
        The asyncio Task running the collector loop, or None if skipped.
    """
    role = os.environ.get("ROLE", "").strip().lower()
    if role and role != "worker":
        logger.info(f"Skipping metrics collector startup (ROLE={role!r}, not 'worker')")
        return None

    global _collector_task
    if _collector_task is not None and not _collector_task.done():
        logger.warning("Metrics collector is already running")
        return _collector_task

    _collector_task = asyncio.create_task(_metrics_loop(interval))
    return _collector_task


def stop_metrics_collector():
    """Cancel the background metrics collector task."""
    global _collector_task
    if _collector_task is not None and not _collector_task.done():
        _collector_task.cancel()
        logger.info("Metrics collector stopped")
    _collector_task = None
