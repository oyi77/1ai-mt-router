"""1ai-payment aggregator checkout + webhook endpoints.

Mirrors the NOWPayments integration in ``app.api.billing`` against the
1ai-payment aggregator (multi-gateway payments). Contract differences:

- amounts arrive already in the smallest currency unit (integer cents), so
  the paid amount is read directly from ``amount`` (no x100 scaling),
- ``order_id`` is an opaque aggregator id (nanoid) used as the idempotency /
  audit payment_id; the subscription context (user/tier/period) is recovered
  from ``project_order_id`` ("{user_id}_{tier}_{billing_period}"),
- webhooks carry ``X-Payment-Event`` + ``X-Payment-Signature`` headers and an
  ``event``/``amount`` body; a success event is ``payment.success``.
"""
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.core.audit import write_audit_log
from app.core.database import get_db
from app.core.exceptions import BadRequestError, ServiceUnavailableError
from app.models.database import AuditLog, Subscription, User
from app.services import payment_service as payment_module
from app.services.billing_service import TIER_CONFIGS

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_payment_service():
    """Return the live 1ai-payment service, or 503 if never initialized."""
    if payment_module.payment_service is None:
        raise ServiceUnavailableError(
            "1ai-payment is not configured", code="payment_not_configured"
        )
    return payment_module.payment_service


#: Action written to the audit log once a subscription is activated.
_ACTIVATION_ACTION = "billing.payment.subscription.activated"
#: Action written to the audit log when a webhook's paid amount is below
#: the amount the checkout was created for.
_AMOUNT_MISMATCH_ACTION = "billing.payment.amount_mismatch"


def _activation_audit_exists(db, user_id, payment_id):
    """Return True if an activation audit entry for this payment already exists.

    Webhook deliveries can be retried by the payment provider, so a duplicate
    of an already-processed payment must not activate the subscription twice.
    """
    if payment_id is None:
        return False
    entries = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == _ACTIVATION_ACTION,
            AuditLog.user_id == user_id,
        )
        .all()
    )
    for entry in entries:
        try:
            details = json.loads(entry.details) if entry.details else {}
        except (ValueError, TypeError):
            continue
        if details.get("payment_id") == payment_id:
            return True
    return False


def _expected_amount_cents(tier, billing_period):
    """Return the expected price in cents for a tier/period, or 0 if unknown."""
    config = TIER_CONFIGS.get(tier)
    if not config:
        return 0
    key = "price_yearly" if billing_period == "yearly" else "price_monthly"
    return config.get(key) or 0


def _parse_paid_amount(value):
    """Return the paid amount in cents, or None if not parseable.

    Unlike NOWPayments, the aggregator reports amounts already in the
    smallest currency unit (integer cents), so no scaling is applied.
    """
    if value is None:
        return None
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


class CheckoutRequest(BaseModel):
    tier: str
    billing_period: str = "monthly"


def get_user_from_token(user: User, db: Session = None) -> User:
    return user


@router.post("/checkout")
async def create_checkout(
    checkout: CheckoutRequest,
    token: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment_service = _require_payment_service()

    tier_config = TIER_CONFIGS.get(checkout.tier)
    if not tier_config:
        raise BadRequestError("Invalid tier", code="invalid_tier")

    amount_cents = (
        tier_config["price_yearly"]
        if checkout.billing_period == "yearly"
        else tier_config["price_monthly"]
    )

    if amount_cents <= 0:
        raise BadRequestError(
            "Cannot checkout free/enterprise tier", code="free_tier_checkout"
        )

    user = get_user_from_token(token, db)
    result = await payment_service.create_payment(
        amount_cents=amount_cents,
        tier=checkout.tier,
        billing_period=checkout.billing_period,
        user_id=user.id,
    )

    if not result:
        raise ServiceUnavailableError(
            "Failed to create payment", code="payment_creation_failed"
        )

    write_audit_log(
        db,
        action="billing.payment.checkout.created",
        user_id=user.id,
        resource_type="payment",
        resource_id=result.get("payment_id"),
        details={
            "tier": checkout.tier,
            "billing_period": checkout.billing_period,
            "amount_cents": amount_cents,
            "gateway": result.get("gateway"),
        },
    )

    return result


@router.post("/webhook")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    payment_service = _require_payment_service()

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise BadRequestError("Malformed webhook payload", code="malformed_payload")

    # The aggregator labels each delivery; a replay of one event must not be
    # able to masquerade as another, so the header must match the body event.
    event = payload.get("event")
    event_header = request.headers.get("x-payment-event", "")
    if event_header and event_header != event:
        raise BadRequestError(
            "Webhook event does not match header", code="event_mismatch"
        )

    signature = request.headers.get("x-payment-signature", "")

    if not payment_service.verify_webhook(raw, signature):
        raise BadRequestError(
            "Invalid payment webhook signature", code="invalid_payment_signature"
        )

    if event != "payment.success":
        logger.info(
            f"1ai-payment: event {event} ignored for order {payload.get('order_id')}"
        )
        return {"status": "ok"}

    # project_order_id format: {user_id}_{tier}_{billing_period}. The
    # aggregator's own order_id is an opaque nanoid, so the subscription
    # context comes from project_order_id.
    project_order_id = payload.get("project_order_id", "")
    parts = project_order_id.split("_", 2)
    try:
        user_id, tier, billing_period = int(parts[0]), parts[1], parts[2]
    except (ValueError, IndexError):
        logger.error(f"1ai-payment: invalid project_order_id: {project_order_id}")
        return {"status": "ok"}
    payment_id = payload.get("order_id")

    # Idempotency: a provider may deliver the same webhook more than once.
    if _activation_audit_exists(db, user_id, payment_id):
        logger.info(
            f"1ai-payment: duplicate webhook for payment {payment_id} "
            f"of user {user_id}, skipping"
        )
        return {"status": "ok"}

    # Amount validation: reject underpaid/fraudulent webhooks before granting
    # access. Only enforced when the tier/period price is known and the
    # payload carries a parseable paid amount.
    expected_cents = _expected_amount_cents(tier, billing_period)
    paid_cents = _parse_paid_amount(payload.get("amount"))
    if expected_cents > 0 and paid_cents is not None and paid_cents < expected_cents:
        write_audit_log(
            db,
            action=_AMOUNT_MISMATCH_ACTION,
            user_id=user_id,
            resource_type="payment",
            resource_id=payment_id,
            details={
                "tier": tier,
                "billing_period": billing_period,
                "expected_cents": expected_cents,
                "paid_cents": paid_cents,
                "event": event,
            },
        )
        logger.error(
            f"1ai-payment: amount mismatch for payment {payment_id} "
            f"of user {user_id}: expected {expected_cents} cents, "
            f"got {paid_cents} cents"
        )
        raise BadRequestError(
            "Payment amount does not match the expected amount",
            code="payment_amount_mismatch",
        )

    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    period_days = 365 if billing_period == "yearly" else 30

    if not sub:
        sub = Subscription(
            user_id=user_id,
            tier=tier,
            status="active",
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow() + timedelta(days=period_days),
        )
        db.add(sub)
    else:
        sub.tier = tier
        sub.status = "active"
        sub.current_period_start = datetime.utcnow()
        sub.current_period_end = datetime.utcnow() + timedelta(days=period_days)
        sub.cancel_at_period_end = False

    try:
        db.commit()
    except IntegrityError:
        # A concurrent webhook delivery for the same user may have already
        # created the subscription (user_id is unique); acknowledge.
        db.rollback()
        logger.warning(
            f"1ai-payment: concurrent activation for user {user_id}, "
            f"payment {payment_id} already committed"
        )
        return {"status": "ok"}

    write_audit_log(
        db,
        action=_ACTIVATION_ACTION,
        user_id=user_id,
        resource_type="subscription",
        resource_id=None,
        details={
            "tier": tier,
            "billing_period": billing_period,
            "payment_id": payment_id,
        },
    )
    logger.info(f"1ai-payment: activated {tier} subscription for user {user_id}")
    return {"status": "ok"}
