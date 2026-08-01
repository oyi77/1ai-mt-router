import asyncio
import logging
import re
import secrets
from typing import Optional

import docker
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ServiceUnavailableError, rollback_on_error
from app.core.logging import log_error
from app.core.docker_client import get_docker_client
from app.models.database import Instance, User

router = APIRouter()
logger = logging.getLogger(__name__)


def get_instance_info(container):
    container.reload()
    ports = container.ports
    return {
        "id": container.id[:12],
        "name": container.name,
        "status": container.status,
        "image": container.image.tags[0] if container.image.tags else "unknown",
        "created": container.attrs["Created"],
        "rpyc_port": ports.get("18812/tcp", [{}])[0].get("HostPort")
        if ports.get("18812/tcp")
        else None,
        "vnc_port": ports.get("6081/tcp", [{}])[0].get("HostPort")
        if ports.get("6081/tcp")
        else None,
        "labels": container.labels,
    }


def get_owned_instance(db: Session, user_id: int, instance_id: str) -> Instance:
    """Resolve an instance owned by ``user_id`` from a short or full id.

    Shared by the instance and VNC routers so ownership is enforced exactly
    once. Raises NotFoundError (never Forbidden) so instance existence is
    not leaked to other users.
    """
    row = (
        db.query(Instance)
        .filter(
            Instance.user_id == user_id,
            or_(
                Instance.id.startswith(instance_id),
                Instance.docker_container_id.startswith(instance_id),
            ),
        )
        .first()
    )
    if row is None:
        raise NotFoundError("Instance not found")
    return row


async def _get_container(client, container_id: str):
    """Fetch a container by id/prefix, mapping docker NotFound to 404."""
    try:
        return await asyncio.to_thread(client.containers.get, container_id)
    except docker.errors.NotFound:
        raise NotFoundError("Instance not found")


async def _instance_info_for(container):
    return await asyncio.to_thread(get_instance_info, container)


class InstanceCreate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    image: Optional[str] = None
    cpu_limit: Optional[float] = Field(default=None, gt=0, le=64)
    memory_limit_mb: Optional[int] = Field(default=None, ge=256, le=262144)
    pids_limit: Optional[int] = Field(default=None, ge=64, le=100000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if value is None:
            return value
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", value):
            raise ValueError("Instance name must match docker container name rules")
        return value


def compute_cpu_percent(cpu_delta, system_delta):
    """M29: clamp first-read/zeroed precpu deltas instead of returning garbage."""
    if cpu_delta <= 0 or system_delta <= 0:
        return 0.0
    return cpu_delta / system_delta * 100.0


@router.get("")
async def list_instances(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    try:
        owned = (
            db.query(Instance).filter(Instance.user_id == user.id).all()
        )
        client = get_docker_client()
        containers = await asyncio.to_thread(
            client.containers.list,
            all=True,
            filters={"label": "mt5-router.instance"},
        )
        matched = [
            c
            for c in containers
            if any(
                (row.docker_container_id and c.id == row.docker_container_id)
                or c.id.startswith(row.id)
                for row in owned
            )
        ]
        return [await _instance_info_for(c) for c in matched]
    except Exception:
        log_error(logger, "Failed to list instances")
        raise ServiceUnavailableError("Instance service unavailable")


@router.get("/{instance_id}")
async def get_instance(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        get_owned_instance(db, user.id, instance_id)
        client = get_docker_client()
        container = await _get_container(client, instance_id)
        return await _instance_info_for(container)
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to get instance %s", instance_id)
        raise ServiceUnavailableError("Instance service unavailable")


@router.post("")
async def create_instance(
    payload: InstanceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        client = get_docker_client()
        instance_name = payload.name or f"mt5-{secrets.token_hex(4)}"

        run_kwargs = dict(
            name=instance_name,
            detach=True,
            ports={"18812/tcp": None, "6081/tcp": None},
            labels={"mt5-router.instance": "true", "mt5-router.created": "auto"},
            shm_size="2gb",
            cap_add=["SYS_ADMIN"],
            restart_policy={"Name": "unless-stopped"},
        )
        if payload.cpu_limit is not None:
            run_kwargs["nano_cpus"] = int(payload.cpu_limit * 1_000_000_000)
        if payload.memory_limit_mb is not None:
            run_kwargs["mem_limit"] = payload.memory_limit_mb * 1024 * 1024
        if payload.pids_limit is not None:
            run_kwargs["pids_limit"] = payload.pids_limit

        container = await asyncio.to_thread(
            client.containers.run, payload.image or settings.MT5_IMAGE, **run_kwargs
        )
        info = await _instance_info_for(container)
        with rollback_on_error(db):
            db.add(
                Instance(
                    id=info["id"],
                    name=info["name"],
                    user_id=user.id,
                    docker_container_id=container.id,
                    status=info["status"],
                    rpyc_port=info["rpyc_port"],
                    vnc_port=info["vnc_port"],
                )
            )
            db.commit()
        return info
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to create instance")
        raise ServiceUnavailableError("Instance service unavailable")


@router.post("/{instance_id}/start")
async def start_instance(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        get_owned_instance(db, user.id, instance_id)
        client = get_docker_client()
        container = await _get_container(client, instance_id)
        await asyncio.to_thread(container.start)
        return {"status": "started", "instance_id": instance_id}
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to start instance %s", instance_id)
        raise ServiceUnavailableError("Instance service unavailable")


@router.post("/{instance_id}/stop")
async def stop_instance(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        get_owned_instance(db, user.id, instance_id)
        client = get_docker_client()
        container = await _get_container(client, instance_id)
        await asyncio.to_thread(container.stop, timeout=30)
        return {"status": "stopped", "instance_id": instance_id}
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to stop instance %s", instance_id)
        raise ServiceUnavailableError("Instance service unavailable")


@router.post("/{instance_id}/restart")
async def restart_instance(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        get_owned_instance(db, user.id, instance_id)
        client = get_docker_client()
        container = await _get_container(client, instance_id)
        await asyncio.to_thread(container.restart, timeout=30)
        return {"status": "restarted", "instance_id": instance_id}
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to restart instance %s", instance_id)
        raise ServiceUnavailableError("Instance service unavailable")


@router.delete("/{instance_id}")
async def delete_instance(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        row = get_owned_instance(db, user.id, instance_id)
        client = get_docker_client()
        container = await _get_container(client, instance_id)
        await asyncio.to_thread(container.remove, force=True)
        db.delete(row)
        db.commit()
        return {"status": "deleted", "instance_id": instance_id}
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to delete instance %s", instance_id)
        raise ServiceUnavailableError("Instance service unavailable")


@router.get("/{instance_id}/logs")
async def get_instance_logs(
    instance_id: str,
    lines: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        get_owned_instance(db, user.id, instance_id)
        client = get_docker_client()
        container = await _get_container(client, instance_id)
        logs = await asyncio.to_thread(container.logs, tail=lines)
        text = logs.decode("utf-8", errors="replace")
        return {"logs": text.split("\n")}
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to fetch logs for instance %s", instance_id)
        raise ServiceUnavailableError("Instance service unavailable")


@router.get("/{instance_id}/stats")
async def get_instance_stats(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        get_owned_instance(db, user.id, instance_id)
        client = get_docker_client()
        container = await _get_container(client, instance_id)
        stats = await asyncio.to_thread(container.stats, stream=False)

        cpu_delta = (
            stats["cpu_stats"]["cpu_usage"]["total_usage"]
            - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        system_delta = (
            stats["cpu_stats"]["system_cpu_usage"]
            - stats["precpu_stats"]["system_cpu_usage"]
        )
        cpu_percent = compute_cpu_percent(cpu_delta, system_delta)

        memory_usage = stats["memory_stats"].get("usage", 0)
        memory_limit = stats["memory_stats"].get("limit", 1)
        memory_percent = (memory_usage / memory_limit * 100.0) if memory_limit > 0 else 0

        return {
            "cpu_percent": round(cpu_percent, 2),
            "memory_usage_mb": round(memory_usage / 1024 / 1024, 2),
            "memory_limit_mb": round(memory_limit / 1024 / 1024, 2),
            "memory_percent": round(memory_percent, 2),
            "network_rx": stats.get("networks", {}).get("eth0", {}).get("rx_bytes", 0),
            "network_tx": stats.get("networks", {}).get("eth0", {}).get("tx_bytes", 0),
        }
    except NotFoundError:
        raise
    except Exception:
        log_error(logger, "Failed to fetch stats for instance %s", instance_id)
        raise ServiceUnavailableError("Instance service unavailable")
