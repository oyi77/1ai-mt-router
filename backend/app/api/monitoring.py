from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session
import asyncio
import psutil
import logging
from datetime import datetime, timedelta

from jose import JWTError, jwt
from app.config import settings
from app.core.database import get_db, SessionLocal
from app.core.docker_client import get_docker_client
from app.core.exceptions import NotFoundError
from app.core.http import SafeJSONResponse
from app.models.database import ServerMetrics, InstanceMetrics, Instance, SSHServer, User
from app.auth.jwt import get_current_user
from app.services.alert_engine import alert_engine

router = APIRouter()
logger = logging.getLogger(__name__)

_PSUTIL_TIMEOUT = 5
_DOCKER_TIMEOUT = 10


def _collect_system_metrics() -> dict:
    """Full system metrics payload (runs in a worker thread)."""
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": {
            "total": memory.total,
            "available": memory.available,
            "percent": memory.percent,
            "used": memory.used,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


def _system_snapshot() -> dict:
    """Compact system snapshot used by the WebSocket stream."""
    return {
        "cpu": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
    }


def _collect_container_metrics(owned_ids: set) -> list:
    """Snapshot live metrics for the user's containers (runs in a worker thread)."""
    client = get_docker_client()
    containers = client.containers.list(filters={"label": "mt5-router.instance"})
    instances = []
    for c in containers:
        if c.id not in owned_ids:
            continue
        try:
            stats = c.stats(stream=False)
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"]
                - stats["precpu_stats"]["system_cpu_usage"]
            )
            cpu_percent = (cpu_delta / system_delta * 100.0) if system_delta > 0 else 0
            memory_usage = stats["memory_stats"].get("usage", 0)
            memory_limit = stats["memory_stats"].get("limit", 1)
            instances.append(
                {
                    "id": c.id[:12],
                    "name": c.name,
                    "status": c.status,
                    "cpu": round(max(0.0, cpu_percent), 2),
                    "memory": round(
                        (memory_usage / memory_limit * 100) if memory_limit > 0 else 0,
                        2,
                    ),
                }
            )
        except Exception:
            pass
    return instances


@router.get("/system", response_class=SafeJSONResponse)
async def get_system_metrics(user: User = Depends(get_current_user)):
    return await asyncio.wait_for(
        asyncio.to_thread(_collect_system_metrics), timeout=_PSUTIL_TIMEOUT
    )


@router.get("/instances", response_class=SafeJSONResponse)
async def get_instances_metrics(user: User = Depends(get_current_user)):
    def collect():
        client = get_docker_client()
        containers = client.containers.list(
            all=True, filters={"label": "mt5-router.instance"}
        )

        metrics = []
        for container in containers:
            try:
                stats = container.stats(stream=False)

                cpu_delta = (
                    stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - stats["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                system_delta = (
                    stats["cpu_stats"]["system_cpu_usage"]
                    - stats["precpu_stats"]["system_cpu_usage"]
                )
                cpu_percent = (cpu_delta / system_delta * 100.0) if system_delta > 0 else 0

                memory_usage = stats["memory_stats"].get("usage", 0)
                memory_limit = stats["memory_stats"].get("limit", 1)

                metrics.append(
                    {
                        "id": container.id[:12],
                        "name": container.name,
                        "status": container.status,
                        "cpu_percent": round(max(0.0, cpu_percent), 2),
                        "memory_usage_mb": round(memory_usage / 1024 / 1024, 2),
                        "memory_limit_mb": round(memory_limit / 1024 / 1024, 2),
                        "memory_percent": round((memory_usage / memory_limit * 100.0), 2)
                        if memory_limit > 0
                        else 0,
                    }
                )
            except Exception as e:
                logger.error(f"Error getting stats for {container.name}: {e}")

        return metrics

    try:
        return await asyncio.wait_for(asyncio.to_thread(collect), timeout=_DOCKER_TIMEOUT)
    except Exception:
        logger.warning("Failed to fetch live instance metrics from Docker", exc_info=True)
        return []


@router.websocket("/stream")
async def metrics_stream(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()
    if not token:
        await websocket.close(code=4401)
        return

    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
    except JWTError:
        user_id = None
    if user_id is None:
        await websocket.close(code=4401)
        return

    owned_ids = set()
    db = SessionLocal()
    try:
        rows = (
            db.query(Instance.docker_container_id)
            .filter(Instance.user_id == int(user_id))
            .all()
        )
        owned_ids = {row[0] for row in rows if row[0]}
    finally:
        db.close()

    await websocket.accept()

    try:
        while True:
            system = await asyncio.wait_for(
                asyncio.to_thread(_system_snapshot), timeout=_PSUTIL_TIMEOUT
            )
            instances = await asyncio.wait_for(
                asyncio.to_thread(_collect_container_metrics, owned_ids),
                timeout=_DOCKER_TIMEOUT,
            )

            await websocket.send_json(
                {
                    "type": "metrics",
                    "system": system,
                    "instances": instances,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            await asyncio.sleep(5)
    except WebSocketDisconnect:
        logger.info("Metrics stream disconnected")
    except asyncio.TimeoutError:
        logger.warning("Metrics stream timed out collecting data")
    except Exception as e:
        logger.error(f"Metrics stream error: {e}")


@router.get("/servers/{server_id}/metrics", response_class=SafeJSONResponse)
async def get_server_metrics_history(
    server_id: int,
    hours: int = Query(default=24, ge=1, le=720),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    server = (
        db.query(SSHServer)
        .filter(SSHServer.id == server_id, SSHServer.user_id == user.id)
        .first()
    )
    if not server:
        raise NotFoundError("Server not found")

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    records = (
        db.query(ServerMetrics)
        .filter(ServerMetrics.server_id == server_id)
        .filter(ServerMetrics.recorded_at >= cutoff)
        .order_by(ServerMetrics.recorded_at)
        .all()
    )
    return [
        {
            "id": r.id,
            "server_id": r.server_id,
            "cpu_percent": r.cpu_percent,
            "memory_total_mb": r.memory_total_mb,
            "memory_used_mb": r.memory_used_mb,
            "disk_total_gb": r.disk_total_gb,
            "disk_used_gb": r.disk_used_gb,
            "network_rx_mb": r.network_rx_mb,
            "network_tx_mb": r.network_tx_mb,
            "docker_containers_total": r.docker_containers_total,
            "docker_containers_running": r.docker_containers_running,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }
        for r in records
    ]


@router.get("/instances/{instance_id}/metrics", response_class=SafeJSONResponse)
async def get_instance_metrics_history(
    instance_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    instance = (
        db.query(Instance)
        .filter(Instance.id == instance_id, Instance.user_id == user.id)
        .first()
    )
    if not instance:
        raise NotFoundError("Instance not found")

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    records = (
        db.query(InstanceMetrics)
        .filter(InstanceMetrics.instance_id == instance_id)
        .filter(InstanceMetrics.recorded_at >= cutoff)
        .order_by(InstanceMetrics.recorded_at)
        .all()
    )
    return [
        {
            "id": r.id,
            "instance_id": r.instance_id,
            "instance_name": r.instance_name,
            "cpu_percent": r.cpu_percent,
            "memory_usage_mb": r.memory_usage_mb,
            "memory_limit_mb": r.memory_limit_mb,
            "memory_percent": r.memory_percent,
            "network_rx_mb": r.network_rx_mb,
            "network_tx_mb": r.network_tx_mb,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }
        for r in records
    ]


@router.get("/alerts", response_class=SafeJSONResponse)
async def get_alerts(user: User = Depends(get_current_user)):
    user_id = user.id
    alerts = [
        {
            "id": rule.id,
            "type": rule.alert_type.value,
            "message": f"{rule.symbol or 'account'} {rule.condition.value} {rule.value}",
            "severity": "warning",
            "instance_id": None,
            "acknowledged": False,
            "created_at": rule.last_triggered.isoformat()
            if rule.last_triggered
            else None,
        }
        for rule in alert_engine.rules.values()
        if rule.user_id == user_id
    ]
    return {"alerts": alerts, "count": len(alerts)}
