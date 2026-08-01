import asyncio
import logging

import httpx
import websockets
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import Response
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.api.instances import get_owned_instance
from app.auth.jwt import get_current_user
from app.config import settings
from app.core.database import SessionLocal, get_db
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import log_error
from app.models.database import User

router = APIRouter()
logger = logging.getLogger(__name__)

# Headers safe to forward to the container's noVNC server; everything else
# (Authorization, Cookie, ...) is dropped so client credentials never leak.
_FORWARD_HEADERS = frozenset(
    {"accept", "accept-encoding", "accept-language", "content-type"}
)


def _resolve_vnc_port(db: Session, user_id: int, instance_id: str) -> int:
    """Resolve the host VNC port from the owner-checked instance row."""
    row = get_owned_instance(db, user_id, instance_id)
    if not row.vnc_port:
        raise BadRequestError("VNC port not exposed")
    return int(row.vnc_port)


def _ws_authenticate(token: str, db: Session):
    """Decode a JWT for WebSocket auth (no HTTP dependency available here).

    Returns the active user row or None; never raises so the caller decides
    how to close the handshake.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        sub = payload.get("sub")
        if sub is None:
            return None
        user = db.query(User).filter(User.id == int(sub)).first()
        if user is None or not user.is_active:
            return None
        return user
    except (JWTError, ValueError, TypeError):
        return None


@router.get("/{instance_id}/status")
async def vnc_status(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        vnc_port = _resolve_vnc_port(db, user.id, instance_id)
    except BadRequestError:
        return {"status": "not_exposed", "instance_id": instance_id}

    async with httpx.AsyncClient(timeout=5) as http_client:
        try:
            resp = await http_client.get(f"http://localhost:{vnc_port}/")
            return {
                "status": "available" if resp.status_code == 200 else "error",
                "instance_id": instance_id,
                "vnc_url": f"/api/v1/vnc/{instance_id}/proxy/vnc.html",
                "port": vnc_port,
            }
        except Exception:
            return {"status": "unreachable", "instance_id": instance_id}


@router.get("/{instance_id}/screenshot")
async def get_screenshot(
    instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    get_owned_instance(db, user.id, instance_id)
    return {
        "message": "Screenshot capture requires VNC snapshot agent",
        "instance_id": instance_id,
    }


@router.get("/{instance_id}/proxy/{path:path}")
async def vnc_proxy(
    instance_id: str,
    path: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reverse proxy HTTP requests to the container's noVNC server."""
    vnc_port = _resolve_vnc_port(db, user.id, instance_id)
    target_url = f"http://localhost:{vnc_port}/{path}"

    if request.query_params:
        target_url += f"?{request.query_params}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in _FORWARD_HEADERS
    }

    async with httpx.AsyncClient(timeout=30) as http_client:
        try:
            resp = await http_client.get(target_url, headers=headers)

            content_type = resp.headers.get("content-type", "application/octet-stream")

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=content_type,
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502, detail="noVNC server not reachable in container"
            )
        except Exception:
            log_error(logger, "VNC proxy error for instance %s", instance_id)
            raise HTTPException(status_code=502, detail="VNC proxy error")


@router.websocket("/{instance_id}/proxy/websockify")
async def vnc_websocket_proxy(websocket: WebSocket, instance_id: str):
    """WebSocket proxy for noVNC -> container's websockify.

    Auth and ownership are enforced before the handshake is accepted, so
    unauthenticated clients get an HTTP 403 rejection and never reach the
    upstream websockify port.
    """
    db = SessionLocal()
    try:
        token = websocket.query_params.get("token", "")
        user = _ws_authenticate(token, db)
        if user is None:
            await websocket.close(code=1008, reason="Not authenticated")
            return
        try:
            vnc_port = _resolve_vnc_port(db, user.id, instance_id)
        except (BadRequestError, NotFoundError):
            await websocket.close(code=1008, reason="Not authenticated")
            return
    finally:
        db.close()

    ws_url = f"ws://localhost:{vnc_port}/websockify"

    await websocket.accept()

    try:
        async with websockets.connect(
            ws_url,
            subprotocols=["binary"],
            max_size=2**23,
            ping_interval=None,
            open_timeout=10,
        ) as upstream:

            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await upstream.send(data)
                except Exception:
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())

    except Exception:
        log_error(logger, "VNC WebSocket proxy error for instance %s", instance_id)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
