"""Regression tests for previously-fixed audit findings (C15, C19, C36, SSRF,
rate limit).

Each test pins behaviour that a prior audit flagged and the codebase has since
fixed. Keeping them together makes the whole set re-runnable with a single
pytest invocation and guards against silent regressions on refactor.

Scope notes / environment assumptions:
- Tests are hermetic: no network calls are made. The SSRF cases use literal
  IPs/hostnames only (blocked or public), so no DNS resolution happens.
- The rate-limit test uses a unique X-Forwarded-For client IP so it never
  pollutes the client-IP bucket shared with other tests (the middleware
  instance is created once at app import and its counters persist).
  _reset_rate_limit_state() drops the middleware's cached Redis client and
  in-memory counters at the start of every test that hits it, so tests are
  order-independent and never reuse a client bound to a closed event loop.
  The assertion is on the HTTP contract (429 + headers); the middleware uses
  Redis when reachable and falls back to an in-memory window otherwise, and
  the contract is the same for both.
- conftest sets a fixed ENCRYPTION_KEY before app import; the encryption
  roundtrip below only needs that key to be self-consistent.
"""

import bcrypt
import inspect
import secrets

import pytest

from app.api import statistics as statistics_api
from app.main import app
from app.middleware.rate_limit import RateLimitMiddleware
from app.models.database import User
from app.services import redis_service
from app.services.encryption import encryption_service
from app.services.mt5_service import MT5Service
from app.services.notification_service import (
    NotificationService,
    validate_webhook_url,
)


def _unique_name(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _reset_rate_limit_state():
    """Drop shared RateLimitMiddleware state before a test that exercises it.

    The middleware instance is created once at app import (main.py adds it via
    add_middleware) and persists across tests in the same process, so its cached
    asyncio Redis client can be bound to a previous test's event loop and die
    with it ("Event loop is closed" on the next test). Resetting here forces a
    fresh client on the current loop and clears the in-memory bucket, making
    these tests order-independent. redis_service's module-level client is
    dropped for the same reason.
    """
    stack = app.middleware_stack
    while stack is not None and not isinstance(stack, RateLimitMiddleware):
        stack = getattr(stack, "app", None)
    if isinstance(stack, RateLimitMiddleware):
        stack._redis = None
        stack._last_redis_attempt = 0.0
        stack.requests.clear()
    redis_service.redis_client = None


# ---------------------------------------------------------------------------
# C15 - passwords are bcrypt-hashed, never stored in plaintext
# ---------------------------------------------------------------------------
def test_c15_bcrypt_roundtrip():
    """Service-level check: hash -> verify works, wrong password rejected."""
    password = "S3cure!regression-pass"
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    assert hashed != password
    assert hashed.startswith("$2b$")
    assert bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    assert not bcrypt.checkpw("wrong-password".encode("utf-8"), hashed.encode("utf-8"))


def test_c15_register_stores_bcrypt_hash(client, db):
    """HTTP-level check: /auth/register persists a bcrypt hash, not plaintext."""
    _reset_rate_limit_state()
    username = _unique_name("b7reg")
    password = f"S3cure!pass{secrets.token_hex(3)}"

    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": password,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]

    user = db.query(User).filter(User.username == username).first()
    assert user is not None
    assert user.hashed_password != password
    assert user.hashed_password.startswith("$2b$")
    assert bcrypt.checkpw(password.encode("utf-8"), user.hashed_password.encode("utf-8"))


# ---------------------------------------------------------------------------
# C19 - MT5 account passwords are Fernet-encrypted before storage
# ---------------------------------------------------------------------------
def test_c19_encrypted_password_roundtrip():
    plaintext = "mt5-account-password-123!@#"
    encrypted = encryption_service.encrypt(plaintext)

    assert encrypted != plaintext
    assert plaintext not in encrypted  # ciphertext never embeds the secret
    assert encryption_service.decrypt(encrypted) == plaintext
    assert encryption_service.decrypt(encryption_service.encrypt("")) == ""


# ---------------------------------------------------------------------------
# C36 - stats endpoints use MT5Service.get_history_deals
# ---------------------------------------------------------------------------
def test_c36_stats_uses_get_history_deals():
    """The old misspelled get_deals_history must not reappear."""
    assert callable(getattr(MT5Service, "get_history_deals", None))
    assert not hasattr(MT5Service, "get_deals_history")

    source = inspect.getsource(statistics_api)
    assert "mt5.get_history_deals" in source
    assert "get_deals_history" not in source


# ---------------------------------------------------------------------------
# Webhook SSRF guard (B17) - validate_webhook_url rejects unsafe targets
# ---------------------------------------------------------------------------
BLOCKED_WEBHOOK_URLS = [
    "http://localhost/webhook",
    "http://127.0.0.1/webhook",
    "http://0.0.0.0/webhook",
    "http://[::1]/webhook",
    "http://10.0.0.1/webhook",
    "http://172.16.0.5/webhook",
    "http://192.168.1.10/webhook",
    "http://169.254.169.254/latest/meta-data/",
    "http://198.51.100.7/webhook",  # TEST-NET-2 documentation range
    "ftp://8.8.8.8/webhook",
    "file:///etc/passwd",
    "http:///no-host",
]


@pytest.mark.parametrize("url", BLOCKED_WEBHOOK_URLS)
def test_ssrf_validate_webhook_url_rejects_blocked(url):
    with pytest.raises(ValueError):
        validate_webhook_url(url)


def test_ssrf_validate_webhook_url_accepts_public_literal():
    # Literal public IP: resolves without DNS, so this stays hermetic.
    assert validate_webhook_url("http://8.8.8.8/webhook") is None


def test_ssrf_add_webhook_rejects_blocked():
    svc = NotificationService()
    with pytest.raises(ValueError):
        svc.add_webhook("bad", "http://169.254.169.254/", ["price_alert"])


# ---------------------------------------------------------------------------
# Rate-limit middleware returns HTTP 429 past the per-minute limit
# ---------------------------------------------------------------------------
def test_rate_limit_returns_429(client):
    _reset_rate_limit_state()
    client_ip = f"198.51.100.{secrets.randbelow(200) + 1}"  # unique per run
    headers = {"X-Forwarded-For": client_ip}

    seen = set()
    for _ in range(150):
        resp = client.get("/health", headers=headers)
        if resp.status_code == 429:
            assert resp.json() == {"detail": "Rate limit exceeded"}
            assert resp.headers.get("X-RateLimit-Limit") == "100"
            assert resp.headers.get("X-RateLimit-Remaining") == "0"
            break
        seen.add(resp.status_code)
    else:
        pytest.fail(
            f"expected HTTP 429 within 150 requests; got statuses {sorted(seen)}"
        )

    assert resp.status_code == 429
