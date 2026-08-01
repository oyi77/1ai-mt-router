"""Tests for the 1ai-payment aggregator checkout + webhook endpoints.

``payment_webhook`` reads the live service from the module attribute
``app.services.payment_service.payment_service`` (None unless startup keys are
set), so tests patch it with a fake. Webhooks are delivered with
``X-Payment-Event`` + ``X-Payment-Signature`` headers and amounts in the
smallest currency unit (integer cents), unlike NOWPayments. Data is seeded
per-test with unique users, and every request uses a unique
``X-Forwarded-For`` so the shared rate-limit bucket never trips.
"""
import hashlib
import hmac
import json
import uuid

import pytest

from app.auth.jwt import create_access_token
from app.models.database import AuditLog, Subscription, User
from app.services.billing_service import TIER_CONFIGS
from app.services.payment_service import PaymentService

WEBHOOK_URL = "/api/v1/payments/webhook"
CHECKOUT_URL = "/api/v1/payments/checkout"
ACTIVATION_ACTION = "billing.payment.subscription.activated"
MISMATCH_ACTION = "billing.payment.amount_mismatch"
CHECKOUT_ACTION = "billing.payment.checkout.created"

# --- per-request fake client IP, so the shared rate-limit bucket never trips ---
_ip_counter = [0]


def _xff():
    _ip_counter[0] += 1
    return f"203.0.113.{_ip_counter[0] % 240 + 1}"


def _headers(event="payment.success"):
    headers = {"X-Forwarded-For": _xff()}
    if event is not None:
        headers["X-Payment-Event"] = event
    return headers


def _make_user(db):
    username = f"pay{uuid.uuid4().hex[:8]}"
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password="x",
        full_name="Payment Webhook",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_headers(db):
    """Authenticated client headers for a fresh per-test user.

    Checkout requires auth; using the shared ``test_user`` fixture here would
    collide with the UNIQUE email/username constraint on the in-memory SQLite
    (StaticPool) once another test in the same run created it.
    """
    user = _make_user(db)
    token = create_access_token(
        {"sub": str(user.id), "username": "tester", "role": "user"}
    )
    return user, {**_headers(None), "Authorization": f"Bearer {token}"}


def _price_cents(tier, billing_period):
    key = "price_yearly" if billing_period == "yearly" else "price_monthly"
    return TIER_CONFIGS[tier][key]


def _webhook_payload(user, tier="basic", billing_period="monthly", **overrides):
    """Build an aggregator webhook payload for a success event at exact price."""
    expected_cents = _price_cents(tier, billing_period)
    payload = {
        "event": "payment.success",
        "gateway": "nowpayments",
        "order_id": uuid.uuid4().hex,
        "project_order_id": f"{user.id}_{tier}_{billing_period}",
        "gateway_reference": uuid.uuid4().hex,
        "status": "success",
        "amount": expected_cents,
        "currency": "usd",
        "payment_method": None,
        "paid_at": None,
        "metadata": None,
        "timestamp": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _audit_entries(db, user_id, action):
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == action, AuditLog.user_id == user_id)
        .all()
    )


def _get_sub(db, user_id):
    return db.query(Subscription).filter(Subscription.user_id == user_id).first()


class FakePaymentService:
    """Stands in for app.services.payment_service.PaymentService."""

    def verify_webhook(self, raw, signature):
        return True


class FakePaymentCreateService(FakePaymentService):
    """Fake implementing create_payment for the checkout endpoint."""

    async def create_payment(self, amount_cents, tier, billing_period, user_id):
        return {
            "payment_url": "https://pay.test/abc",
            "payment_id": "pay_123",
            "gateway": "nowpayments",
        }


@pytest.fixture
def payment_service(client, monkeypatch):
    fake = FakePaymentService()
    monkeypatch.setattr("app.services.payment_service.payment_service", fake)
    return fake


@pytest.fixture
def payment_create_service(client, monkeypatch):
    fake = FakePaymentCreateService()
    monkeypatch.setattr("app.services.payment_service.payment_service", fake)
    return fake


def test_payment_webhook_success_activates(client, db, payment_service):
    user = _make_user(db)
    payload = _webhook_payload(user)
    resp = client.post(WEBHOOK_URL, json=payload, headers=_headers())
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    sub = _get_sub(db, user.id)
    assert sub is not None
    assert sub.tier == "basic"
    assert sub.status == "active"

    activations = _audit_entries(db, user.id, ACTIVATION_ACTION)
    assert len(activations) == 1
    assert json.loads(activations[0].details)["payment_id"] == payload["order_id"]


def test_payment_webhook_duplicate_is_idempotent(client, db, payment_service):
    user = _make_user(db)
    payload = _webhook_payload(user)

    first = client.post(WEBHOOK_URL, json=payload, headers=_headers())
    second = client.post(WEBHOOK_URL, json=payload, headers=_headers())
    assert first.status_code == 200
    assert second.status_code == 200

    assert len(_audit_entries(db, user.id, ACTIVATION_ACTION)) == 1
    subs = db.query(Subscription).filter(Subscription.user_id == user.id).all()
    assert len(subs) == 1


def test_payment_webhook_underpaid_rejected(client, db, payment_service):
    user = _make_user(db)
    underpaid = _price_cents("basic", "monthly") - 1
    payload = _webhook_payload(user, amount=underpaid)

    resp = client.post(WEBHOOK_URL, json=payload, headers=_headers())
    assert resp.status_code == 400
    assert resp.json()["code"] == "payment_amount_mismatch"

    mismatches = _audit_entries(db, user.id, MISMATCH_ACTION)
    assert len(mismatches) == 1
    details = json.loads(mismatches[0].details)
    assert details["expected_cents"] == _price_cents("basic", "monthly")
    assert details["paid_cents"] == underpaid
    assert mismatches[0].resource_id == payload["order_id"]

    assert len(_audit_entries(db, user.id, ACTIVATION_ACTION)) == 0
    assert _get_sub(db, user.id) is None


def test_payment_webhook_valid_signature_activates(client, db, monkeypatch):
    service = PaymentService(
        api_key="test-key",
        base_url="http://localhost:3100",
        gateway="nowpayments",
        webhook_secret="test-secret",
    )
    monkeypatch.setattr("app.services.payment_service.payment_service", service)

    user = _make_user(db)
    payload = _webhook_payload(user)
    raw = json.dumps(payload).encode()
    sig = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    headers = {
        **_headers(),
        "Content-Type": "application/json",
        "X-Payment-Signature": sig,
    }

    resp = client.post(WEBHOOK_URL, data=raw, headers=headers)
    assert resp.status_code == 200
    assert _get_sub(db, user.id) is not None


def test_payment_webhook_invalid_signature_rejected(client, db, monkeypatch):
    service = PaymentService(
        api_key="test-key",
        base_url="http://localhost:3100",
        gateway="nowpayments",
        webhook_secret="test-secret",
    )
    monkeypatch.setattr("app.services.payment_service.payment_service", service)

    user = _make_user(db)
    payload = _webhook_payload(user)
    headers = {**_headers(), "X-Payment-Signature": "deadbeef"}

    resp = client.post(WEBHOOK_URL, json=payload, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_payment_signature"
    assert _get_sub(db, user.id) is None


def test_payment_webhook_event_mismatch_rejected(client, db, payment_service):
    user = _make_user(db)
    payload = _webhook_payload(user, event="payment.failed")

    resp = client.post(WEBHOOK_URL, json=payload, headers=_headers("payment.success"))
    assert resp.status_code == 400
    assert resp.json()["code"] == "event_mismatch"
    assert _get_sub(db, user.id) is None


def test_payment_webhook_malformed_order_id_ignored(
    client, db, payment_service
):
    user = _make_user(db)
    payload = _webhook_payload(user, project_order_id="not-an-int_basic_monthly")

    resp = client.post(WEBHOOK_URL, json=payload, headers=_headers())
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert _get_sub(db, user.id) is None
    assert len(_audit_entries(db, user.id, ACTIVATION_ACTION)) == 0


def test_payment_checkout_creates_payment(
    client, db, payment_create_service
):
    user, headers = _auth_headers(db)
    resp = client.post(
        CHECKOUT_URL,
        json={"tier": "basic", "billing_period": "monthly"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "payment_url": "https://pay.test/abc",
        "payment_id": "pay_123",
        "gateway": "nowpayments",
    }

    checkouts = _audit_entries(db, user.id, CHECKOUT_ACTION)
    assert len(checkouts) == 1
    details = json.loads(checkouts[0].details)
    assert details["tier"] == "basic"
    assert details["billing_period"] == "monthly"
    assert details["amount_cents"] == _price_cents("basic", "monthly")


def test_payment_checkout_free_tier_rejected(
    client, db, payment_create_service
):
    _, headers = _auth_headers(db)
    resp = client.post(CHECKOUT_URL, json={"tier": "free"}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "free_tier_checkout"
