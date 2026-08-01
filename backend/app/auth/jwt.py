import hashlib
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
from jose import JWTError, jwt
from fastapi import HTTPException, Depends, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.orm import Session
from app.config import settings
from app.core.database import get_db

if TYPE_CHECKING:
    from app.models.database import User

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_api_key_token(user_id: int, api_key_id: int, permissions: list):
    to_encode = {
        "sub": str(user_id),
        "api_key_id": api_key_id,
        "permissions": permissions,
        "type": "api_key",
    }
    expire = datetime.utcnow() + timedelta(days=365)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


def verify_token_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
):
    """Like verify_token but returns None instead of raising on a missing or
    invalid Authorization header, so API-key-only requests can fall through to
    the api-key branch."""
    if credentials is None:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        return payload
    except JWTError:
        return None


async def verify_api_key(
    api_key: Optional[str] = Security(api_key_header), db: Session = Depends(get_db)
):
    if not api_key:
        return None

    from app.models.database import ApiKey, User

    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    db_key = (
        db.query(ApiKey)
        .filter(ApiKey.key == key_hash, ApiKey.is_active.is_(True))
        .first()
    )
    if not db_key:
        return None

    if db_key.expires_at and db_key.expires_at < datetime.utcnow():
        return None

    db_key.last_used = datetime.utcnow()
    db.commit()

    user = db.query(User).filter(User.id == db_key.user_id).first()
    return user


async def get_current_user_or_api_key(
    token: Optional[dict] = Depends(verify_token_optional),
    api_key_user: Optional["User"] = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    if token:
        from app.models.database import User

        user = db.query(User).filter(User.id == int(token["sub"])).first()
        return user
    elif api_key_user:
        return api_key_user
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")


def get_current_user(
    token: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    try:
        user_id = int(token["sub"])
    except (ValueError, TypeError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid token")

    from app.models.database import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
