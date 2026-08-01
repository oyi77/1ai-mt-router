"""B6 tests for the billing API (app.api.billing).

Billing endpoints read the live service from the module attribute
``app.services.billing_service.billing_service`` (None unless startup keys are
set), so tests either leave it None (the "not configured" path) or patch it
with a FakeBillingService. All data is seeded per-test with unique users.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt import create_access_token
from app.config import settings
from app.main import app
from app.models.database import Subscription, User


# --- per-request fake client IP, so the shared rate-limit bucket never trips ---
_ip_counter = [0]


def _xff():
    _ip_counter[0] += 1
    return f"203.0.113.{_ip_counter[0] % 240 + 1}"


def _headers(user_id):
    token = create_access_token(
        {"sub": str(user_id), "username": "tester", "role": "user"}
    )
    return {"Authorization": f"Bearer {token}", "X-Forwarded-For": _xff()}


def _plain_headers():
    return {"X-Forwarded-For": _xff()}


def _make_user(db):
    username = f"b6b{uuid.uuid4().hex[:8]}"
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password="x",
        full_name="B6 Billing",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_sub(db, user, *, stripe_customer_id=None, stripe_subscription_id=None):
    sub = Subscription(
        user_id=user.id,
        tier="basic",
        status="active",
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        cancel_at_period_end=False,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


class FakeBillingService:
    """Stands in for app.services.billing_service.BillingService.

    Endpoints call methods with keyword args only. None -> falsy, BaseException
    -> raise, anything else -> return. Matches the FakeMT5Service pattern used
    in test_stats.py.
    """

    _responses = {}
    _calls = []

    def __getattr__(self, name):
        def _method(*args, **kwargs):
            FakeBillingService._calls.append((name, args, kwargs))
            val = FakeBillingService._responses.get(name)
            if isinstance(val, BaseException):
                raise val
            return val

        return _method


@pytest.fixture(autouse=True)
def _fake_billing():
    FakeBillingService._responses = {}
    FakeBillingService._calls = []
    # billing_service stays None unless a test patches it.


def _patch_service(monkeypatch):
    fake = FakeBillingService()
    monkeypatch.setattr("app.services.billing_service.billing_service", fake)
    return fake


def _url(path):
    return f"/api/v1/billing{path}"


# --- public / unauthenticated -------------------------------------------------


def test_tiers_public(client, db):
    resp = client.get(_url("/tiers"))
    assert resp.status_code == 200
    body = resp.json()
    assert "basic" in body
    assert "enterprise" not in body


def test_subscription_free_default(client, db):
    user = _make_user(db)
    resp = client.get(_url("/subscription"), headers=_headers(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "free"
    assert body["status"] == "active"


# --- checkout -----------------------------------------------------------------


def test_checkout_503_not_configured(client, db):
    user = _make_user(db)
    resp = client.post(
        _url("/checkout"), json={"tier": "basic"}, headers=_headers(user.id)
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "billing_not_configured"


def test_checkout_400_invalid_tier(client, db, monkeypatch):
    _patch_service(monkeypatch)
    user = _make_user(db)
    resp = client.post(
        _url("/checkout"), json={"tier": "nope"}, headers=_headers(user.id)
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_tier"


def test_checkout_400_price_not_configured(client, db, monkeypatch):
    _patch_service(monkeypatch)
    FakeBillingService._responses["create_customer"] = "cus_123"
    user = _make_user(db)
    resp = client.post(
        _url("/checkout"), json={"tier": "basic"}, headers=_headers(user.id)
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "billing_not_configured"


def test_checkout_success(client, db, monkeypatch):
    _patch_service(monkeypatch)
    FakeBillingService._responses["create_customer"] = "cus_123"
    FakeBillingService._responses["create_checkout_session"] = {
        "session_id": "cs_123",
        "url": "https://checkout.stripe.com/c/pay/cs_123",
    }
    monkeypatch.setattr(settings, "STRIPE_PRICE_BASIC_MONTHLY", "price_123")
    user = _make_user(db)

    resp = client.post(
        _url("/checkout"), json={"tier": "basic"}, headers=_headers(user.id)
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "cs_123"

    # customer created first (keyword args), then the checkout session
    assert FakeBillingService._calls[0][0] == "create_customer"
    assert FakeBillingService._calls[0][2]["email"] == user.email
    assert FakeBillingService._calls[0][2]["name"] == "B6 Billing"
    assert FakeBillingService._calls[0][2]["user_id"] == user.id
    assert FakeBillingService._calls[1][0] == "create_checkout_session"
    assert FakeBillingService._calls[1][2]["customer_id"] == "cus_123"
    assert FakeBillingService._calls[1][2]["price_id"] == "price_123"
    assert FakeBillingService._calls[1][2]["trial_days"] == 14
    assert FakeBillingService._calls[1][2]["tier"] == "basic"
    assert "CHECKOUT_SESSION_ID" in FakeBillingService._calls[1][2]["success_url"]

    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    assert sub is not None
    assert sub.stripe_customer_id == "cus_123"


# --- portal / cancel ----------------------------------------------------------


def test_portal_400_no_billing_account(client, db, monkeypatch):
    _patch_service(monkeypatch)
    user = _make_user(db)
    resp = client.get(_url("/portal"), headers=_headers(user.id))
    assert resp.status_code == 400
    assert resp.json()["code"] == "no_billing_account"


def test_portal_success(client, db, monkeypatch):
    _patch_service(monkeypatch)
    FakeBillingService._responses["create_customer_portal_session"] = (
        "https://billing.stripe.com/p/session/x"
    )
    user = _make_user(db)
    _make_sub(db, user, stripe_customer_id="cus_123")

    resp = client.get(_url("/portal"), headers=_headers(user.id))
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://billing.stripe.com/p/session/x"
    assert FakeBillingService._calls[0][2]["customer_id"] == "cus_123"


def test_cancel_400_no_subscription(client, db, monkeypatch):
    _patch_service(monkeypatch)
    user = _make_user(db)
    resp = client.post(_url("/cancel"), headers=_headers(user.id))
    assert resp.status_code == 400
    assert resp.json()["code"] == "no_active_subscription"


def test_cancel_success(client, db, monkeypatch):
    _patch_service(monkeypatch)
    FakeBillingService._responses["cancel_subscription"] = True
    user = _make_user(db)
    _make_sub(db, user, stripe_subscription_id="sub_123")

    resp = client.post(_url("/cancel"), headers=_headers(user.id))
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "canceled",
        "cancel_at_period_end": True,
        "message": "Subscription will end at period end",
    }
    assert FakeBillingService._calls[0][0] == "cancel_subscription"
    assert FakeBillingService._calls[0][1] == ("sub_123",)
    assert FakeBillingService._calls[0][2] == {"cancel_at_period_end": True}

    db.expire_all()
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    assert sub.cancel_at_period_end is True


# --- usage --------------------------------------------------------------------


def test_usage_free_fallback(client, db):
    user = _make_user(db)
    resp = client.get(_url("/usage"), headers=_headers(user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "free"
    assert body["usage"]["servers"]["current"] == 0
    assert body["usage"]["instances"]["current"] == 0
    assert body["within_limits"] is True
    assert body["violations"] == []


# --- NOWPayments (not configured -> 503) --------------------------------------


def test_nowpayments_checkout_503(client, db):
    user = _make_user(db)
    resp = client.post(
        _url("/nowpayments/checkout"), json={"tier": "basic"}, headers=_headers(user.id)
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "nowpayments_not_configured"


def test_nowpayments_webhook_503(client):
    resp = client.post(_url("/nowpayments/webhook"), json={}, headers=_plain_headers())
    assert resp.status_code == 503
    assert resp.json()["code"] == "nowpayments_not_configured"


# --- Stripe webhook -----------------------------------------------------------


def test_stripe_webhook_not_configured(client):
    resp = client.post(_url("/webhook"), headers=_plain_headers())
    assert resp.status_code == 200
    assert resp.json() == {"status": "error", "message": "Billing not configured"}


def test_stripe_webhook_missing_signature(client, db, monkeypatch):
    _patch_service(monkeypatch)
    resp = client.post(_url("/webhook"), headers=_plain_headers())
    assert resp.status_code == 200
    assert resp.json() == {"status": "error", "message": "Missing signature"}


def test_stripe_webhook_bare_name(client, db, monkeypatch):
    # Regression test for the fixed defect: app/api/billing.py:492 previously
    # called the bare name `billing_service.handle_webhook`, which raised
    # NameError (the module only binds `billing_module`/`nowpayments_module`)
    # and turned the request into a sanitized 500 with the fake never reached.
    # It now routes through `billing_module.billing_service.handle_webhook` and
    # returns the service result to the caller.
    #
    # Header must be exactly `Stripe-Signature`: the endpoint reads
    # `request.headers.get("stripe-signature")` (no "x-" prefix), so
    # `X-Stripe-Signature` would fall through to the "Missing signature" branch.
    _patch_service(monkeypatch)
    FakeBillingService._responses["handle_webhook"] = {
        "status": "processed",
        "type": "checkout.session.completed",
    }
    resp = client.post(
        _url("/webhook"), headers={**_plain_headers(), "Stripe-Signature": "t"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "processed", "type": "checkout.session.completed"}
    name, args, kwargs = FakeBillingService._calls[0]
    assert name == "handle_webhook"
    assert args[:2] == (b"", "t")
    assert kwargs == {}
