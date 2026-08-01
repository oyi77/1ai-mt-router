from fastapi import APIRouter, Depends, Query
from typing import Optional, List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import datetime
import asyncio
import logging
import random
import psutil
import platform

from app.core.database import get_db
from app.core.docker_client import get_docker_client
from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.models.database import SSHServer, ServerMetrics, Instance, User
from app.auth.jwt import get_current_user
from app.services import ssh_service as ssh_module

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_ssh_service():
    """Return the live SSH service, or 503 if it was never initialized.

    ``init_ssh_service`` rebinds the module-level ``ssh_service`` global in
    ``app.services.ssh_service`` during startup, so consumers must read the
    module attribute at call time instead of importing the name directly
    (a direct import freezes it at ``None``).
    """
    if ssh_module.ssh_service is None:
        raise ServiceUnavailableError(message="SSH service not initialized")
    return ssh_module.ssh_service


def _collect_local_health() -> dict:
    """Collect health metrics for the local Docker server."""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    client = get_docker_client()
    containers = client.containers.list(
        all=True, filters={"label": "mt5-router.instance"}
    )

    instances = []
    for c in containers:
        ports = c.ports
        instances.append(
            {
                "id": c.id[:12],
                "name": c.name,
                "status": c.status,
                "rpyc_port": ports.get("18812/tcp", [{}])[0].get("HostPort")
                if ports.get("18812/tcp")
                else None,
                "vnc_port": ports.get("6081/tcp", [{}])[0].get("HostPort")
                if ports.get("6081/tcp")
                else None,
            }
        )

    return {
        "server_id": 0,
        "status": "healthy",
        "metrics": {
            "cpu_percent": round(cpu_percent, 1),
            "memory": {
                "total": memory.total,
                "used": memory.used,
                "percent": round(memory.percent, 1),
            },
            "disk": {
                "total": f"{disk.total / (1024**3):.1f}G",
                "used": f"{disk.used / (1024**3):.1f}G",
                "percent": round(disk.percent, 1),
            },
            "hostname": platform.node(),
            "containers_total": len(containers),
            "containers_running": sum(
                1 for c in containers if c.status == "running"
            ),
        },
        "instances": instances,
        "checked_at": datetime.utcnow().isoformat(),
    }


@router.get("/local/health")
async def local_server_health(user: User = Depends(get_current_user)):
    """Get health metrics for the local Docker server."""
    try:
        return await asyncio.to_thread(_collect_local_health)
    except Exception:
        logger.error("Failed to get local server health", exc_info=True)
        raise ServiceUnavailableError(message="Failed to check local server health")


class ServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    host: str = Field(..., min_length=1)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(..., min_length=1)
    private_key: Optional[str] = None
    password: Optional[str] = None
    use_key_auth: bool = True
    # Local socket path (or unix:// URL) by default. ``ssh://user@host[:port]``
    # remote transports are supported by docker-py (7.x + paramiko installed)
    # and pass through via ``get_docker_client(base_url=...)``.
    docker_socket: str = "/var/run/docker.sock"


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    private_key: Optional[str] = None
    password: Optional[str] = None
    use_key_auth: Optional[bool] = None
    is_active: Optional[bool] = None


class ServerResponse(BaseModel):
    id: int
    name: str
    host: str
    port: int
    username: str
    use_key_auth: bool
    docker_socket: str
    is_active: bool
    health_status: str
    last_health_check: Optional[datetime]
    created_at: datetime


class ServerHealthResponse(BaseModel):
    server_id: int
    status: str
    metrics: Optional[dict] = None
    instances: Optional[List[dict]] = None
    checked_at: str


class InstanceCreate(BaseModel):
    name: Optional[str] = None
    image: str = "lprett/mt5linux:mt5-installed"


def get_ssh_connection(server: SSHServer, service):
    private_key = None
    password = None

    if server.use_key_auth and server.encrypted_private_key:
        private_key = service.decrypt_secret(server.encrypted_private_key)
    elif server.encrypted_password:
        password = service.decrypt_secret(server.encrypted_password)

    client = service.create_client(
        host=server.host,
        port=server.port,
        username=server.username,
        private_key=private_key,
        password=password,
    )

    if not client:
        raise ServiceUnavailableError(
            message="Cannot connect to server. Check credentials."
        )

    return client


def _get_owned_server(db: Session, server_id: int, user) -> SSHServer:
    server = (
        db.query(SSHServer)
        .filter(SSHServer.id == server_id, SSHServer.user_id == user.id)
        .first()
    )
    if not server:
        raise NotFoundError(message="Server not found")
    return server


def _get_owned_instance(
    db: Session, server_id: int, instance_name: str, user
) -> Instance:
    instance = (
        db.query(Instance)
        .filter(
            Instance.server_id == server_id,
            Instance.name == instance_name,
            Instance.user_id == user.id,
        )
        .first()
    )
    if not instance:
        raise NotFoundError(message="Instance not found")
    return instance


def _ensure_active(server: SSHServer) -> None:
    if not server.is_active:
        raise BadRequestError(message="Server is disabled")


@router.post("")
async def create_server(
    server_data: ServerCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ssh_service = _require_ssh_service()

    private_key_encrypted = None
    password_encrypted = None

    if server_data.use_key_auth:
        if not server_data.private_key:
            raise BadRequestError(
                message="Private key required for key authentication"
            )
        private_key_encrypted = ssh_service.encrypt_secret(server_data.private_key)
    else:
        if not server_data.password:
            raise BadRequestError(
                message="Password required for password authentication"
            )
        password_encrypted = ssh_service.encrypt_secret(server_data.password)

    test_client = await asyncio.to_thread(
        ssh_service.create_client,
        host=server_data.host,
        port=server_data.port,
        username=server_data.username,
        private_key=server_data.private_key if server_data.use_key_auth else None,
        password=server_data.password if not server_data.use_key_auth else None,
        timeout=15,
    )

    if not test_client:
        raise BadRequestError(
            message="Cannot connect to server. Check credentials."
        )

    test_client.close()

    server = SSHServer(
        user_id=user.id,
        name=server_data.name,
        host=server_data.host,
        port=server_data.port,
        username=server_data.username,
        encrypted_private_key=private_key_encrypted,
        encrypted_password=password_encrypted,
        use_key_auth=server_data.use_key_auth,
        docker_socket=server_data.docker_socket,
        health_status="unknown",
    )

    db.add(server)
    db.commit()
    db.refresh(server)

    return {
        "id": server.id,
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "status": "created",
        "message": "Server added successfully. Run health check to verify connection.",
    }


@router.get("")
async def list_servers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    servers = db.query(SSHServer).filter(SSHServer.user_id == user.id).all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "host": s.host,
            "port": s.port,
            "username": s.username,
            "use_key_auth": s.use_key_auth,
            "is_active": s.is_active,
            "health_status": s.health_status,
            "last_health_check": s.last_health_check,
            "created_at": s.created_at,
        }
        for s in servers
    ]


@router.get("/{server_id}")
async def get_server(
    server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    server = _get_owned_server(db, server_id, user)

    return {
        "id": server.id,
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "username": server.username,
        "use_key_auth": server.use_key_auth,
        "docker_socket": server.docker_socket,
        "is_active": server.is_active,
        "health_status": server.health_status,
        "last_health_check": server.last_health_check,
        "created_at": server.created_at,
    }


@router.put("/{server_id}")
async def update_server(
    server_id: int,
    update: ServerUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    server = _get_owned_server(db, server_id, user)

    ssh_service = _require_ssh_service()

    if (
        update.use_key_auth is True
        and not update.private_key
        and not server.encrypted_private_key
    ):
        raise BadRequestError(message="Private key required for key authentication")

    if update.name is not None:
        server.name = update.name
    if update.host is not None:
        server.host = update.host
    if update.port is not None:
        server.port = update.port
    if update.username is not None:
        server.username = update.username
    if update.is_active is not None:
        server.is_active = update.is_active

    if update.private_key is not None:
        server.encrypted_private_key = ssh_service.encrypt_secret(update.private_key)
        server.use_key_auth = True
    if update.password is not None:
        server.encrypted_password = ssh_service.encrypt_secret(update.password)
    if update.use_key_auth is not None:
        server.use_key_auth = update.use_key_auth

    db.commit()
    return {"status": "updated"}


@router.delete("/{server_id}")
async def delete_server(
    server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    server = _get_owned_server(db, server_id, user)

    # Delete child rows first: Instance and ServerMetrics hold FKs to
    # ssh_servers with no cascade, so deleting the parent first would raise a
    # foreign-key violation on PostgreSQL.
    db.query(Instance).filter(Instance.server_id == server.id).delete(
        synchronize_session=False
    )
    db.query(ServerMetrics).filter(ServerMetrics.server_id == server.id).delete(
        synchronize_session=False
    )

    db.delete(server)
    db.commit()
    return {"status": "deleted"}


@router.post("/{server_id}/health")
async def check_server_health(
    server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    server = _get_owned_server(db, server_id, user)
    _ensure_active(server)

    ssh_service = _require_ssh_service()

    client = await asyncio.to_thread(get_ssh_connection, server, ssh_service)

    try:
        health = await asyncio.to_thread(ssh_service.check_health, client)
        metrics = await asyncio.to_thread(ssh_service.get_server_metrics, client)
        instances = await asyncio.to_thread(ssh_service.list_instances, client)

        server.health_status = health["status"]
        server.last_health_check = datetime.utcnow()
        db.commit()

        if health["status"] == "healthy":
            metric = ServerMetrics(
                server_id=server.id,
                cpu_percent=metrics.get("cpu_percent", 0),
                memory_total_mb=metrics.get("memory", {}).get("total", 0),
                memory_used_mb=metrics.get("memory", {}).get("used", 0),
                disk_total_gb=0,
                disk_used_gb=0,
                docker_containers_total=metrics.get("containers_total", 0),
                docker_containers_running=metrics.get("containers_running", 0),
            )
            db.add(metric)
            db.commit()

        return {
            "server_id": server.id,
            "status": health["status"],
            "metrics": metrics,
            "instances": instances,
            "checked_at": datetime.utcnow().isoformat(),
        }
    finally:
        client.close()


@router.get("/{server_id}/instances")
async def list_server_instances(
    server_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    server = _get_owned_server(db, server_id, user)
    _ensure_active(server)

    ssh_service = _require_ssh_service()

    client = await asyncio.to_thread(get_ssh_connection, server, ssh_service)

    try:
        instances = await asyncio.to_thread(ssh_service.list_instances, client)
        return instances
    finally:
        client.close()


@router.post("/{server_id}/instances")
async def create_instance_on_server(
    server_id: int,
    instance_data: InstanceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    server = _get_owned_server(db, server_id, user)
    _ensure_active(server)

    ssh_service = _require_ssh_service()

    client = await asyncio.to_thread(get_ssh_connection, server, ssh_service)

    try:
        instance_name = instance_data.name or f"mt5-{random.randint(1000, 9999)}"

        result = await asyncio.to_thread(
            ssh_service.run_mt5_instance, client, instance_name, instance_data.image
        )

        if not result["success"]:
            logger.error(
                "Failed to create instance: server=%s error=%s",
                server.id,
                result.get("error"),
            )
            raise ServiceUnavailableError(message="Failed to create instance")

        instance = Instance(
            id=result["container_id"][:12],
            name=instance_name,
            user_id=user.id,
            server_id=server.id,
            docker_container_id=result["container_id"],
            status="running",
            rpyc_port=result.get("rpyc_port"),
            vnc_port=result.get("vnc_port"),
        )
        db.add(instance)
        db.commit()

        return {
            "id": result["container_id"],
            "name": instance_name,
            "server": server.name,
            "status": "created",
            "rpyc_port": result.get("rpyc_port"),
            "vnc_port": result.get("vnc_port"),
        }
    finally:
        client.close()


@router.post("/{server_id}/instances/{instance_name}/{action}")
async def control_instance_on_server(
    server_id: int,
    instance_name: str,
    action: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    server = _get_owned_server(db, server_id, user)
    _ensure_active(server)
    _get_owned_instance(db, server_id, instance_name, user)

    ssh_service = _require_ssh_service()

    client = await asyncio.to_thread(get_ssh_connection, server, ssh_service)

    try:
        result = await asyncio.to_thread(
            ssh_service.control_instance, client, instance_name, action
        )

        if not result["success"]:
            logger.error(
                "Failed to control instance: server=%s instance=%s action=%s error=%s",
                server.id, instance_name, action, result.get("error"),
            )
            return {
                "success": False,
                "action": action,
                "output": result.get("output", ""),
                "error": "Failed to control instance",
            }
        return result
    finally:
        client.close()


@router.get("/{server_id}/instances/{instance_name}/logs")
async def get_instance_logs(
    server_id: int,
    instance_name: str,
    lines: int = Query(100, ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    server = _get_owned_server(db, server_id, user)
    _ensure_active(server)
    _get_owned_instance(db, server_id, instance_name, user)

    ssh_service = _require_ssh_service()

    client = await asyncio.to_thread(get_ssh_connection, server, ssh_service)

    try:
        logs = await asyncio.to_thread(
            ssh_service.get_instance_logs, client, instance_name, lines
        )
        return {"logs": logs.split("\n")}
    finally:
        client.close()
