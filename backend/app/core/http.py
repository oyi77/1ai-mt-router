"""HTTP layer helpers: safe JSON serialization and central exception handlers.

Cross-bundle contract (SAA readiness plan, bundle B10): this module is the
single place that maps application errors to HTTP responses. Bundles register
it with ``register_exception_handlers(app)`` during app bootstrap (bundle B2)
and API bundles raise :class:`AppError` subclasses instead of leaking raw
internals via ``detail=str(e)`` (finding M36).

Float serialization: Starlette's ``JSONResponse`` uses ``allow_nan=False`` by
default, so a single ``float('inf')`` in a payload would 500 the whole
response. ``SafeJSONResponse`` renders non-finite floats as JSON literals
(``Infinity`` / ``-Infinity`` / ``NaN``) so reporting endpoints never crash
over an extreme value.
"""

import json
import logging
import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


class SafeJSONEncoder(json.JSONEncoder):
    """JSON encoder tolerant of values common in API payloads.

    Handles non-finite floats, ``datetime``/``date``, ``Decimal`` and ``UUID``;
    everything else falls back to the standard encoder.
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, float) and not math.isfinite(obj):
            if math.isnan(obj):
                return "NaN"
            return "Infinity" if obj > 0 else "-Infinity"
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            if obj.is_finite():
                return float(obj)
            return str(obj)
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


def safe_json_dumps(data: Any, **kwargs: Any) -> str:
    """Serialize ``data`` with :class:`SafeJSONEncoder`.

    ``ensure_ascii=False`` keeps non-ASCII payloads readable; callers may pass
    additional ``json.dumps`` options (``indent``, ``sort_keys``, ...).
    """
    return json.dumps(data, cls=SafeJSONEncoder, ensure_ascii=False, **kwargs)


class SafeJSONResponse(JSONResponse):
    """``JSONResponse`` that renders non-finite floats instead of failing."""

    def render(self, content: Any) -> bytes:
        return safe_json_dumps(content).encode("utf-8")


def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Render an :class:`AppError` as a structured error body.

    Body keeps ``detail`` at the top level for frontend compatibility and adds
    a machine-readable ``code`` plus optional structured ``details``.
    """
    body: Dict[str, Any] = {"detail": exc.detail, "code": exc.code}
    if exc.details is not None:
        body["details"] = exc.details
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers,
    )


def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log the full traceback, return a sanitized 500.

    Attaches ``request_id`` when present (set by the request-id middleware in
    bundle B9); the field is omitted when no middleware ran.
    """
    # exc_info=exc (not exc_info=True): the sync handler runs in a threadpool
    # thread where sys.exc_info() is empty, so True would log no traceback.
    logger.error(
        "Unhandled error on %s %s", request.method, request.url.path, exc_info=exc
    )
    body: Dict[str, Any] = {"detail": "Internal server error"}
    request_id: Optional[str] = getattr(request.state, "request_id", None)
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=500, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the central error handlers onto ``app``.

    ``AppError`` must be registered by class so it wins the MRO lookup over
    the base ``HTTPException`` handler. ``Exception`` is the catch-all that
    turns anything unexpected into a sanitized 500.
    """
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
