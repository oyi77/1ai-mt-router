"""Audit trail writer.

Writes ``audit_logs`` rows via the :class:`AuditLog` model (B4). Rows are
committed immediately so the trail survives failure of the audited
operation. Used by auth (B11), billing (B15), admin (B16), webhook (B17)
and monitoring flows.

Non-string ``details`` are JSON-serialised so callers can pass structured
context (e.g. ``{"ip": "..."}``) without extra work.
"""

import json

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import AuditLog


def write_audit_log(
    db: Session,
    *,
    action: str,
    user_id: int = None,
    resource_type: str = None,
    resource_id: str = None,
    details=None,
    ip_address: str = None,
) -> AuditLog:
    """Create, commit and return an audit log entry."""
    if details is not None and not isinstance(details, str):
        details = json.dumps(details, default=str)
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=details,
        ip_address=ip_address,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _client_ip(request) -> Optional[str]:
    """Resolve the real client IP from a FastAPI request.

    Mirrors ``rate_limit.RateLimitMiddleware._client_ip``: ``X-Forwarded-For``
    is only honoured when the socket peer is a trusted proxy (or trust is
    configured open with ``"*"``); otherwise the header can be spoofed by an
    attacker to misattribute another client's audit trail.
    """
    if request is None:
        return None
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    trusted = settings.trusted_proxies
    if forwarded and ("*" in trusted or peer in trusted):
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = peer
    return client_ip or "unknown"


def log_user_action(
    db: Session,
    *,
    user_id: int,
    action: str,
    resource_type: str = None,
    resource_id: str = None,
    details=None,
    request=None,
) -> AuditLog:
    """Convenience wrapper that pulls the client IP from a FastAPI request."""
    ip_address = _client_ip(request)
    return write_audit_log(
        db,
        action=action,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
    )
