"""Tests for the admin API (app.api.admin).

The tier update endpoint persists overrides to data/tier_overrides.json, so
tests redirect TIER_OVERRIDES_PATH to a per-test tmp file. Admin endpoints
are guarded by require_admin (JWT role == "admin"), so tokens are minted
with an explicit admin role.
"""
import uuid

import pytest

from app.api import admin as admin_module
from app.auth.jwt import create_access_token
from app.models.database import User

ADMIN_BASE = "/api/v1/admin"

# --- per-request fake client IP, so the shared rate-limit bucket never trips ---
_ip_counter = [0]


def _xff():
    _ip_counter[0] += 1
    return f"203.0.113.{_ip_counter[0] % 240 + 1}"


def _admin_headers(user_id):
    token = create_access_token(
        {"sub": str(user_id), "username": "admin", "role": "admin"}
    )
    return {"Authorization": f"Bearer {token}", "X-Forwarded-For": _xff()}


def _user_headers(user_id):
    token = create_access_token(
        {"sub": str(user_id), "username": "tester", "role": "user"}
    )
    return {"Authorization": f"Bearer {token}", "X-Forwarded-For": _xff()}


def _make_user(db):
    username = f"adm{uuid.uuid4().hex[:8]}"
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def tier_overrides_file(tmp_path, monkeypatch):
    """Redirect tier override persistence to an isolated temp file."""
    path = tmp_path / "tier_overrides.json"
    monkeypatch.setattr(admin_module, "TIER_OVERRIDES_PATH", str(path))
    return path


def test_update_tier_rejects_boolean_price_monthly(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.put(
        f"{ADMIN_BASE}/tiers/basic",
        json={"price_monthly": True},
        headers=_admin_headers(user.id),
    )
    # bool is rejected by the schema-level StrictInt validator before the
    # handler runs, so FastAPI returns a 422 validation error.
    assert resp.status_code == 422
    assert "non-negative integer" in resp.text
    # Nothing persisted.
    assert not tier_overrides_file.exists()


def test_update_tier_rejects_boolean_price_yearly(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.put(
        f"{ADMIN_BASE}/tiers/basic",
        json={"price_yearly": False},
        headers=_admin_headers(user.id),
    )
    assert resp.status_code == 422
    assert "non-negative integer" in resp.text
    assert not tier_overrides_file.exists()


def test_update_tier_rejects_boolean_limit_value(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.put(
        f"{ADMIN_BASE}/tiers/basic",
        json={"limits": {"max_instances": True}},
        headers=_admin_headers(user.id),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_limit"
    assert not tier_overrides_file.exists()


def test_update_tier_accepts_valid_integers(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.put(
        f"{ADMIN_BASE}/tiers/basic",
        json={"price_monthly": 1234, "price_yearly": 12340, "limits": {"max_instances": 7}},
        headers=_admin_headers(user.id),
    )
    assert resp.status_code == 200
    assert resp.json()["tier"]["price_monthly"] == 1234
    assert resp.json()["tier"]["price_yearly"] == 12340
    assert resp.json()["tier"]["limits"]["max_instances"] == 7
    # Overrides were persisted to the (isolated) override file.
    overrides = admin_module._load_tier_overrides()
    assert overrides["basic"]["price_monthly"] == 1234
    assert overrides["basic"]["limits"]["max_instances"] == 7


def test_update_tier_requires_admin(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.put(
        f"{ADMIN_BASE}/tiers/basic",
        json={"price_monthly": 100},
        headers=_user_headers(user.id),
    )
    assert resp.status_code == 403
    assert not tier_overrides_file.exists()


def test_update_tier_unknown_tier_returns_404(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.put(
        f"{ADMIN_BASE}/tiers/nope",
        json={"price_monthly": 100},
        headers=_admin_headers(user.id),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "tier_not_found"


def test_update_tier_negative_price_rejected(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.put(
        f"{ADMIN_BASE}/tiers/basic",
        json={"price_monthly": -5},
        headers=_admin_headers(user.id),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_price"
    assert not tier_overrides_file.exists()


def test_list_tiers_still_works(client, db, tier_overrides_file):
    user = _make_user(db)
    resp = client.get(f"{ADMIN_BASE}/tiers", headers=_admin_headers(user.id))
    assert resp.status_code == 200
    assert "basic" in resp.json()["tiers"]
