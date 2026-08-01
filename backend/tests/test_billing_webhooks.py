"""F6 tests: NOWPayments webhook idempotency and paid-amount validation.

``nowpayments_webhook`` reads the live service from the module attribute
``app.services.nowpayments_service.nowpayments_service`` (None unless startup
keys are set), so tests patch it with a fake whose ``verify_webhook`` always
succeeds. Data is seeded per-test with unique users, and every request uses a
unique ``X-Forwarded-For`` so the shared rate-limit bucket never trips.
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import AuditLog, Subscription, User
from app.services.billing_service import TIER_CONFIGS

URL = "/api/v1/billing/nowpayments/webhook"
ACTIVATION_ACTION = "billing.nowpayments.subscription.activated"
MISMATCH_ACTION = "billing.nowpayments.amount_mismatch"

# --- per-request fake client IP, so the shared rate-limit bucket never trips ---
_ip_counter = [0]


def _xff():
    _ip_counter[0] += 1
    return f"203.0.113.{_ip_counter[0] % 240 + 1}"


def _headers():
    return {"X-Forwarded-For": _xff()}


def _make_user(db):
    username = f"f6b{uuid.uuid4().hex[:8]}"
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password="x",
        full_name="F6 Webhook",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class FakeNowPaymentsService:
    """Stands in for app.services.nowpayments_service.NowPaymentsService."""

    def verify_webhook(self, raw, signature):
        return True


@pytest.fixture
def nowpayments(client, monkeypatch):
    fake = FakeNowPaymentsService()
    monkeypatch.setattr("app.services.nowpayments_service.nowpayments_service", fake)
    return fake


def _price_cents(tier, billing_period):
    key = "price_yearly" if billing_period == "yearly" else "price_monthly"
    return TIER_CONFIGS[tier][key]


def _webhook_payload(user, tier="basic", billing_period="monthly", **overrides):
    """Build an IPN payload for a finished payment of the exact price."""
    expected_cents = _price_cents(tier, billing_period)
    payload = {
        "payment_id": uuid.uuid4().hex,
        "payment_status": "finished",
        "pay_status": "finished",
        "price_amount": f"{expected_cents / 100:.2f}",
        "price_currency": "usd",
        "pay_amount": f"{expected_cents / 100:.2f}",
        "actually_paid": f"{expected_cents / 100:.2f}",
        "pay_currency": "usdttrc20",
        "order_id": f"{user.id}_{tier}_{billing_period}",
        "order_description": "test",
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


def test_nowpayments_webhook_full_payment_activates(client, db, nowpayments):
    user = _make_user(db)
    payload = _webhook_payload(user)

    resp = client.post(URL, json=payload, headers=_headers())

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    sub = _get_sub(db, user.id)
    assert sub is not None
    assert sub.tier == "basic"
    assert sub.status == "active"

    activations = _audit_entries(db, user.id, ACTIVATION_ACTION)
    assert len(activations) == 1
    details = json.loads(activations[0].details)
    assert details["payment_id"] == payload["payment_id"]
    assert details["tier"] == "basic"
    assert details["billing_period"] == "monthly"


def test_nowpayments_webhook_duplicate_payment_is_idempotent(client, db, nowpayments):
    user = _make_user(db)
    payload = _webhook_payload(user)

    first = client.post(URL, json=payload, headers=_headers())
    second = client.post(URL, json=payload, headers=_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"status": "ok"}
    assert second.json() == {"status": "ok"}

    # Exactly one activation entry and one subscription row for the payment.
    assert len(_audit_entries(db, user.id, ACTIVATION_ACTION)) == 1
    subs = db.query(Subscription).filter(Subscription.user_id == user.id).all()
    assert len(subs) == 1


def test_nowpayments_webhook_underpaid_rejected(client, db, nowpayments):
    user = _make_user(db)
    expected_cents = _price_cents("basic", "monthly")
    payload = _webhook_payload(
        user, pay_amount=f"{(expected_cents - 1) / 100:.2f}",
        actually_paid=f"{(expected_cents - 1) / 100:.2f}",
    )

    resp = client.post(URL, json=payload, headers=_headers())

    assert resp.status_code == 400
    assert resp.json()["code"] == "payment_amount_mismatch"

    # Mismatch recorded in the audit trail; no activation, no subscription.
    mismatches = _audit_entries(db, user.id, MISMATCH_ACTION)
    assert len(mismatches) == 1
    details = json.loads(mismatches[0].details)
    assert details["expected_cents"] == expected_cents
    assert details["paid_cents"] == expected_cents - 1
    assert mismatches[0].resource_id == payload["payment_id"]
    assert len(_audit_entries(db, user.id, ACTIVATION_ACTION)) == 0
    assert _get_sub(db, user.id) is None


def test_nowpayments_webhook_no_amount_fields_skips_validation(client, db, nowpayments):
    user = _make_user(db)
    payload = _webhook_payload(user)
    for field in ("pay_amount", "actually_paid", "payment_amount", "paid_amount"):
        payload.pop(field, None)

    resp = client.post(URL, json=payload, headers=_headers())

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert _get_sub(db, user.id) is not None
    assert len(_audit_entries(db, user.id, ACTIVATION_ACTION)) == 1


def test_nowpayments_webhook_updates_existing_subscription(client, db, nowpayments):
    user = _make_user(db)
    sub = Subscription(
        user_id=user.id,
        tier="basic",
        status="active",
        current_period_start=None,
        current_period_end=None,
    )
    db.add(sub)
    db.commit()

    payload = _webhook_payload(user, tier="pro", billing_period="yearly")

    resp = client.post(URL, json=payload, headers=_headers())

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    subs = db.query(Subscription).filter(Subscription.user_id == user.id).all()
    assert len(subs) == 1
    assert subs[0].id == sub.id
    assert subs[0].tier == "pro"
    assert subs[0].status == "active"
    assert len(_audit_entries(db, user.id, ACTIVATION_ACTION)) == 1
