"""B6: Authentication flow tests (register / login / 2FA / password reset)."""
import bcrypt
import pyotp
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from app.auth.jwt import create_access_token
from app.models.database import User

_ip = [0]


def _xff():
    _ip[0] += 1
    return f"203.0.113.{_ip[0] % 240 + 1}"


def _headers(**extra):
    h = {"X-Forwarded-For": _xff()}
    h.update(extra)
    return h


def _make_user(db, *, email=None, username=None, password="Passw0rd!x", **kwargs):
    email = email or f"{uuid4().hex[:12]}@example.com"
    username = username or f"user{uuid4().hex[:8]}"
    kwargs.setdefault("is_verified", True)
    user = User(
        email=email,
        username=username,
        hashed_password=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, password


def _token(user):
    return create_access_token(
        {"sub": str(user.id), "username": user.username, "role": "user"}
    )


def _bearer(user):
    return {"Authorization": f"Bearer {_token(user)}"}


@pytest.fixture
def user(db):
    return _make_user(db)[0]


# --- register ---------------------------------------------------------------


def test_register_success(client):
    email = f"{uuid4().hex[:12]}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": f"user{uuid4().hex[:8]}", "password": "Passw0rd!x"},
        headers=_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["requires_verification"] is False
    assert body["user"]["email"] == email


def test_register_duplicate_email_400(db, client):
    u, _ = _make_user(db)
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": u.email, "username": f"user{uuid4().hex[:8]}", "password": "Passw0rd!x"},
        headers=_headers(),
    )
    assert resp.status_code == 400


def test_register_duplicate_username_400(db, client):
    u, _ = _make_user(db)
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": f"{uuid4().hex[:12]}@example.com", "username": u.username, "password": "Passw0rd!x"},
        headers=_headers(),
    )
    assert resp.status_code == 400


def test_register_invalid_email_422(client):
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "username": f"user{uuid4().hex[:8]}", "password": "Passw0rd!x"},
        headers=_headers(),
    )
    assert resp.status_code == 422


# --- login ------------------------------------------------------------------


def test_login_success(client, db):
    u, pwd = _make_user(db)
    resp = client.post(
        "/api/v1/auth/login", json={"username": u.username, "password": pwd}, headers=_headers()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == u.username


def test_login_unknown_user_401(client):
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": f"nobody{uuid4().hex[:8]}", "password": "whatever"},
        headers=_headers(),
    )
    assert resp.status_code == 401


def test_login_wrong_password_401(client, db):
    u, _ = _make_user(db)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": u.username, "password": "WrongPassw0rd"},
        headers=_headers(),
    )
    assert resp.status_code == 401
    db.refresh(u)
    assert u.failed_login_attempts >= 1


def test_login_disabled_account_403(client, db):
    u, pwd = _make_user(db, is_active=False)
    resp = client.post(
        "/api/v1/auth/login", json={"username": u.username, "password": pwd}, headers=_headers()
    )
    assert resp.status_code == 403


def test_login_locked_account_423(client, db):
    u, pwd = _make_user(db)
    for _ in range(8):
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": u.username, "password": "WrongPassw0rd"},
            headers=_headers(),
        )
        assert resp.status_code in (401, 423)
    # 5 failed attempts trigger lockout; after 8 the correct password is refused.
    resp = client.post(
        "/api/v1/auth/login", json={"username": u.username, "password": pwd}, headers=_headers()
    )
    assert resp.status_code == 423


def test_login_unverified_account_requires_verification(client, db):
    u, pwd = _make_user(db, is_verified=False)
    resp = client.post(
        "/api/v1/auth/login", json={"username": u.username, "password": pwd}, headers=_headers()
    )
    assert resp.status_code == 200
    assert resp.json()["requires_verification"] is True


# --- 2FA --------------------------------------------------------------------


def test_2fa_full_flow(client, db):
    u, pwd = _make_user(db)
    hdr = {**_headers(), **_bearer(u)}

    resp = client.post("/api/v1/auth/2fa/setup", headers=hdr)
    assert resp.status_code == 200
    secret = resp.json()["secret"]
    assert secret

    code = pyotp.TOTP(secret).now()
    resp = client.post("/api/v1/auth/2fa/verify", json={"code": code}, headers=hdr)
    assert resp.status_code == 200
    assert resp.json()["status"] == "enabled"

    # setup again while enabled -> 400
    resp = client.post("/api/v1/auth/2fa/setup", headers=hdr)
    assert resp.status_code == 400

    # login without code -> requires_2fa
    resp = client.post(
        "/api/v1/auth/login", json={"username": u.username, "password": pwd}, headers=_headers()
    )
    assert resp.status_code == 200
    assert resp.json()["requires_2fa"] is True

    # wrong code -> 401
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": u.username, "password": pwd, "two_factor_code": "000000"},
        headers=_headers(),
    )
    assert resp.status_code == 401

    # correct code -> 200
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": u.username, "password": pwd, "two_factor_code": pyotp.TOTP(secret).now()},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]

    # disable -> login without code succeeds again
    resp = client.post("/api/v1/auth/2fa/disable", headers=hdr)
    assert resp.status_code == 200
    resp = client.post(
        "/api/v1/auth/login", json={"username": u.username, "password": pwd}, headers=_headers()
    )
    assert resp.status_code == 200


def test_2fa_verify_without_setup_400(client, db):
    u, _ = _make_user(db)
    resp = client.post(
        "/api/v1/auth/2fa/verify",
        json={"code": "123456"},
        headers={**_headers(), **_bearer(u)},
    )
    assert resp.status_code == 400


# --- email verification -----------------------------------------------------


def test_verify_email_success(client, db):
    u = User(
        email=f"{uuid4().hex[:12]}@example.com",
        username=f"user{uuid4().hex[:8]}",
        hashed_password=bcrypt.hashpw(b"Passw0rd!x", bcrypt.gensalt()).decode(),
        is_verified=False,
        verification_token="tok123",
        verification_token_expires=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(u)
    db.commit()
    resp = client.post(
        "/api/v1/auth/verify-email", json={"token": "tok123"}, headers=_headers()
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "verified"


def test_verify_email_bad_token_400(client, db):
    u, _ = _make_user(db, verification_token="tok456",
                      verification_token_expires=datetime.utcnow() + timedelta(hours=1))
    resp = client.post(
        "/api/v1/auth/verify-email", json={"token": "not-the-token"}, headers=_headers()
    )
    assert resp.status_code == 400


# --- password reset ---------------------------------------------------------


def test_forgot_password_unknown_email_200(client):
    resp = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": f"missing{uuid4().hex[:8]}@example.com"},
        headers=_headers(),
    )
    assert resp.status_code == 200


def test_forgot_password_invalid_email_422(client):
    resp = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "not-an-email"},
        headers=_headers(),
    )
    assert resp.status_code == 422


def test_password_reset_full_flow(client, db):
    u, pwd = _make_user(db)
    resp = client.post(
        "/api/v1/auth/forgot-password", json={"email": u.email}, headers=_headers()
    )
    assert resp.status_code == 200
    db.refresh(u)
    assert u.reset_token

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": u.reset_token, "new_password": "NewPassw0rd!"},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "reset"

    # old password no longer works, new one does
    resp = client.post(
        "/api/v1/auth/login", json={"username": u.username, "password": pwd}, headers=_headers()
    )
    assert resp.status_code == 401
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": u.username, "password": "NewPassw0rd!"},
        headers=_headers(),
    )
    assert resp.status_code == 200


def test_password_reset_expired_token_400(client, db):
    u, _ = _make_user(db)
    resp = client.post(
        "/api/v1/auth/forgot-password", json={"email": u.email}, headers=_headers()
    )
    assert resp.status_code == 200
    db.refresh(u)
    u.reset_token_expires = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": u.reset_token, "new_password": "NewPassw0rd!"},
        headers=_headers(),
    )
    assert resp.status_code == 400


# --- /me and /security ------------------------------------------------------


def test_me(client, db):
    u, _ = _make_user(db)
    resp = client.get("/api/v1/auth/me", headers={**_headers(), **_bearer(u)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == u.username
    assert body["role"] == "user"


def test_security_info(client, db):
    u, _ = _make_user(db)
    resp = client.get("/api/v1/auth/security", headers={**_headers(), **_bearer(u)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["two_factor_enabled"] is False
    assert body["email_verified"] is True
