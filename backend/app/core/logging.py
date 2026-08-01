"""Structured JSON logging + request-id support.

App modules keep using stdlib ``logging.getLogger(__name__)``; the root
logger is configured once via :func:`setup_logging` (replaces
``logging.basicConfig``). Log records are emitted as single-line JSON
with ``level`` / ``ts`` / ``logger`` / ``msg`` and redacted secrets.

Request-id hook: :class:`RequestIdMiddleware` sets a contextvar from the
``X-Request-ID`` header (or a generated id), the :class:`RequestIdFilter`
copies it onto log records, and the formatter includes it in the JSON
output. App wiring (B2) registers the middleware.
"""

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Keys whose values must never appear in logs (case-insensitive).
_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "jwt",
    "encrypted_password",
    "encrypted_private_key",
    "encryption_key",
    "private_key",
)

_SENSITIVE_KEY_RE = re.compile(
    r"\b(" + "|".join(_SENSITIVE_KEYS) + r")\b\s*[=:]\s*([^\s,}\]]+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+")


def redact_text(text: str) -> str:
    """Redact sensitive values from a log message before it is emitted."""
    if not text:
        return text
    text = _SENSITIVE_KEY_RE.sub(r"\1=***REDACTED***", text)
    text = _BEARER_RE.sub("Bearer=***REDACTED***", text)
    return text


_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_id(request_id: str):
    """Set the request id for the current context; returns a token for reset."""
    return _request_id_var.set(request_id)


class RequestIdFilter(logging.Filter):
    """Copies the active request id onto every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class RedactingFormatter(logging.Formatter):
    """Single-line JSON formatter with ts/level/logger/msg + request_id."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            payload["exc_type"] = exc_type.__name__
            payload["exc_message"] = redact_text(str(exc_value))
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with the JSON formatter (idempotent).

    Call once at app startup instead of ``logging.basicConfig``.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter())
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)


def log_error(logger: logging.Logger, message: str, *args, **kwargs) -> None:
    """Log at ERROR with ``exc_info=True`` (emits exception details as JSON)."""
    kwargs.setdefault("exc_info", True)
    logger.error(message, *args, **kwargs)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attaches a request id to the context and the response.

    Reuses the ``X-Request-ID`` header when present, otherwise generates
    one. The id is visible to log records via :class:`RequestIdFilter`.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex[:16]
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response
