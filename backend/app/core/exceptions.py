"""Central error types and rollback hygiene for the MT5 Router API.

Cross-bundle contract (SAA readiness plan, bundle B10): API bundles raise
``AppError`` subclasses instead of leaking raw internals via
``detail=str(e)`` (finding M36), and wrap session work in
``rollback_on_error`` so failed transactions never leave a dirty session.
"""

from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session


class AppError(HTTPException):
    """Base application error.

    Carries an HTTP ``status_code``, a stable machine-readable ``code`` and
    an optional structured ``details`` payload. ``message`` is the public,
    pre-sanitized text shown to clients — never interpolate raw exception
    text into it.

    Subclassing :class:`HTTPException` means the default FastAPI
    ``{"detail": ...}`` response still works as a fallback until
    ``app.core.http.register_exception_handlers`` is wired, and existing
    ``except HTTPException`` blocks keep behaving.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.details = details


class BadRequestError(AppError):
    def __init__(
        self,
        message: str = "Bad request",
        code: str = "bad_request",
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, code, message, details, headers)


class UnauthorizedError(AppError):
    def __init__(
        self,
        message: str = "Not authenticated",
        code: str = "unauthorized",
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, code, message, details, headers)


class ForbiddenError(AppError):
    def __init__(
        self,
        message: str = "Insufficient permissions",
        code: str = "forbidden",
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, code, message, details, headers)


class NotFoundError(AppError):
    def __init__(
        self,
        message: str = "Not found",
        code: str = "not_found",
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, code, message, details, headers)


class ConflictError(AppError):
    def __init__(
        self,
        message: str = "Conflict",
        code: str = "conflict",
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status.HTTP_409_CONFLICT, code, message, details, headers)


class ServiceUnavailableError(AppError):
    def __init__(
        self,
        message: str = "Service unavailable",
        code: str = "service_unavailable",
        details: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(status.HTTP_503_SERVICE_UNAVAILABLE, code, message, details, headers)


@contextmanager
def rollback_on_error(db: Session) -> Iterator[Session]:
    """Yield ``db``; roll back the session if the block raises, then re-raise.

    Ensures a failed transaction never leaves the session dirty for the next
    request sharing it (see ``app.core.database.get_db``). Usage::

        with rollback_on_error(db):
            db.add(thing)
            db.commit()
    """
    try:
        yield db
    except Exception:
        db.rollback()
        raise
