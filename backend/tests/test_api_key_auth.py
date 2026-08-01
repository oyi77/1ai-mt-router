"""F1: X-API-Key authentication tests.

Requests carrying only the X-API-Key header must authenticate through
get_current_user_or_api_key; bearer-only requests keep working; requests with
neither must be rejected.
"""
import hashlib
import secrets
from uuid import uuid4

from app.auth.jwt import create_access_token
from app.models.database import ApiKey, User

# GET /api/v1/notifications/webhooks is a pure read on get_current_user_or_api_key.
_NOTIFICATIONS_URL = "/api/v1/notifications/webhooks"


def _make_user(db):
    """Create a user with unique credentials (the shared test_user fixture is
    single-use per process, so files needing several users must create their
    own)."""
    user = User(
        email=f"{uuid4().hex[:12]}@example.com",
        username=f"user{uuid4().hex[:8]}",
        hashed_password="$2b$12$LQv3c1yqBo9SkvXS7mNGeOQWjwQwQwQwQwQwQwQwQwQwQwQwQwQw",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_api_key(db, user):
    plain_key = f"mtr_{secrets.token_hex(32)}"
    api_key = ApiKey(
        key=hashlib.sha256(plain_key.encode("utf-8")).hexdigest(),
        name="test-key",
        user_id=user.id,
        permissions="read,trade",
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return plain_key


def test_api_key_only_request_authenticates(client, db):
    """A request with only the X-API-Key header must NOT be rejected with
    401/403 — the api-key branch must be reached despite the missing bearer."""
    user = _make_user(db)
    plain_key = _make_api_key(db, user)
    resp = client.get(_NOTIFICATIONS_URL, headers={"X-API-Key": plain_key})
    assert resp.status_code not in (401, 403)


def test_bearer_only_request_authenticates(client, db):
    """Bearer-only requests keep working."""
    user = _make_user(db)
    token = create_access_token(data={"sub": str(user.id)})
    resp = client.get(
        _NOTIFICATIONS_URL, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


def test_no_credentials_raises_401(client):
    """No credentials at all -> 401 (current behavior preserved)."""
    resp = client.get(_NOTIFICATIONS_URL)
    assert resp.status_code in (401, 403)


def test_invalid_api_key_raises_401(client):
    """An unknown X-API-Key does not authenticate."""
    resp = client.get(_NOTIFICATIONS_URL, headers={"X-API-Key": "mtr_not_a_real_key"})
    assert resp.status_code in (401, 403)
