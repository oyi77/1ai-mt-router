import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.jwt import get_current_user
from app.config import settings
from app.core.audit import write_audit_log
from app.core.database import get_db
from app.core.exceptions import (
    BadRequestError,
    ServiceUnavailableError,
)
from app.models.database import (
    User,
    Subscription,
    AuditLog,
    SSHServer,
    Instance as InstanceModel,
)
from app.services.billing_service import TIER_CONFIGS
from app.services import billing_service as billing_module
from app.services import nowpayments_service as nowpayments_module

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_billing_service():
    """Return the live billing service, or 503 if never initialized.

    ``init_billing_service`` rebinds the module-level ``billing_service``
    global in ``app.services.billing_service`` during startup, so consumers
    must read the module attribute at call time instead of importing the name
    directly (a direct import freezes it at ``None``).
    """
    if billing_module.billing_service is None:
        raise ServiceUnavailableError(
            "Billing not configured", code="billing_not_configured"
        )
    return billing_module.billing_service


def _require_nowpayments_service():
    """Return the live NOWPayments service, or 503 if never initialized.

    ``init_nowpayments_service`` rebinds the module-level ``nowpayments_service``
    global in ``app.services.nowpayments_service`` during startup, so consumers
    must read the module attribute at call time instead of importing the name
    directly (a direct import freezes it at ``None``).
    """
    if nowpayments_module.nowpayments_service is None:
        raise ServiceUnavailableError(
            "NOWPayments is not configured", code="nowpayments_not_configured"
        )
    return nowpayments_module.nowpayments_service


#: Action written to the audit log once a subscription is activated.
_ACTIVATION_ACTION = "billing.nowpayments.subscription.activated"
#: Action written to the audit log when a webhook's paid amount is below
#: the amount the checkout was created for.
_AMOUNT_MISMATCH_ACTION = "billing.nowpayments.amount_mismatch"
#: Amount fields NOWPayments IPN payloads may carry, in order of preference.
#: The first present, parseable field wins.
_PAID_AMOUNT_FIELDS = ("pay_amount", "actually_paid", "payment_amount", "paid_amount")


def _parse_paid_amount_cents(payload):
    """Return the paid amount in cents, or None if no amount field is usable.

    NOWPayments prices are quoted in USD but settled in a crypto currency, so
    the IPN amounts (``pay_amount``/``actually_paid``) are in that currency's
    unit (USDT, ~1:1 with USD here). Amounts are parsed via Decimal and
    converted to integer cents. If no field parses, we deliberately do not
    guess and report None so validation is skipped.
    """
    for field in _PAID_AMOUNT_FIELDS:
        value = payload.get(field)
        if value is None:
            continue
        try:
            return int(Decimal(str(value)) * 100)
        except (InvalidOperation, ValueError):
            continue
    return None


def _activation_audit_exists(db, user_id, payment_id):
    """Return True if an activation audit entry for this payment already exists.

    Webhook deliveries can be retried by the payment provider, so a duplicate
    of an already-processed payment must not activate the subscription twice.
    The audit log is the only record keyed by ``payment_id``, so we scan the
    user's activation entries and compare the parsed JSON payload.
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


class CheckoutRequest(BaseModel):
    tier: str
    billing_period: str = "monthly"


def get_user_from_token(user: User, db: Session = None) -> User:
    return user


@router.get("/tiers")
async def list_tiers():
    return {
        name: {
            "name": config["name"],
            "price_monthly": config["price_monthly"],
            "price_yearly": config["price_yearly"],
            "limits": config["limits"],
            "features": config["features"],
        }
        for name, config in TIER_CONFIGS.items()
        if name != "enterprise"
    }


@router.get("/subscription")
async def get_subscription(
    token: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    user = get_user_from_token(token, db)
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()

    if not sub:
        return {
            "tier": "free",
            "status": "active",
            "limits": TIER_CONFIGS["free"]["limits"],
            "features": TIER_CONFIGS["free"]["features"],
        }

    config = TIER_CONFIGS.get(sub.tier, TIER_CONFIGS["free"])

    return {
        "tier": sub.tier,
        "status": sub.status,
        "current_period_end": sub.current_period_end.isoformat()
        if sub.current_period_end
        else None,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "stripe_customer_id": sub.stripe_customer_id,
        "limits": config["limits"],
        "features": config["features"],
    }


@router.post("/checkout")
async def create_checkout(
    checkout: CheckoutRequest,
    token: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    billing_service = _require_billing_service()

    tier_config = TIER_CONFIGS.get(checkout.tier)
    if not tier_config:
        raise BadRequestError("Invalid tier", code="invalid_tier")

    user = get_user_from_token(token, db)
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()

    if not sub or not sub.stripe_customer_id:
        customer_id = billing_service.create_customer(
            email=user.email, name=user.full_name or user.username, user_id=user.id
        )
        if not customer_id:
            raise ServiceUnavailableError("Failed to create customer", code="customer_creation_failed")

        if not sub:
            sub = Subscription(user_id=user.id, stripe_customer_id=customer_id)
            db.add(sub)
        else:
            sub.stripe_customer_id = customer_id
        db.commit()
    else:
        customer_id = sub.stripe_customer_id

    billing_period = checkout.billing_period
    price_id = getattr(
        settings, f"STRIPE_PRICE_{checkout.tier.upper()}_{billing_period.upper()}", ""
    )

    if not price_id:
        raise BadRequestError(
            "Billing for this tier and billing period is not configured",
            code="billing_not_configured",
        )

    session = billing_service.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=f"{settings.BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.BASE_URL}/billing/cancel",
        trial_days=14,
        tier=checkout.tier,
        billing_period=billing_period,
        user_id=user.id,
    )

    if not session:
        raise ServiceUnavailableError(
            "Failed to create checkout session", code="checkout_session_failed"
        )

    write_audit_log(
        db,
        action="billing.checkout.created",
        user_id=user.id,
        resource_type="checkout",
        resource_id=session.get("session_id"),
        details={"tier": checkout.tier, "billing_period": billing_period},
    )

    return session


@router.get("/portal")
async def customer_portal(
    token: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    billing_service = _require_billing_service()

    user = get_user_from_token(token, db)
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()

    if not sub or not sub.stripe_customer_id:
        raise BadRequestError("No billing account found", code="no_billing_account")

    portal_url = billing_service.create_customer_portal_session(
        customer_id=sub.stripe_customer_id,
        return_url=f"{settings.BASE_URL}/billing",
    )

    if not portal_url:
        raise ServiceUnavailableError(
            "Failed to create portal session", code="portal_session_failed"
        )

    return {"url": portal_url}


@router.post("/cancel")
async def cancel_subscription(
    immediate: bool = False,
    token: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    billing_service = _require_billing_service()

    user = get_user_from_token(token, db)
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()

    if not sub or not sub.stripe_subscription_id:
        raise BadRequestError("No active subscription", code="no_active_subscription")

    success = billing_service.cancel_subscription(
        sub.stripe_subscription_id, cancel_at_period_end=not immediate
    )

    if not success:
        raise ServiceUnavailableError(
            "Failed to cancel subscription", code="subscription_cancel_failed"
        )

    sub.cancel_at_period_end = not immediate
    db.commit()

    write_audit_log(
        db,
        action="billing.subscription.canceled",
        user_id=user.id,
        resource_type="subscription",
        resource_id=sub.stripe_subscription_id,
        details={"immediate": immediate},
    )

    return {
        "status": "canceled",
        "cancel_at_period_end": not immediate,
        "message": "Subscription will end at period end"
        if not immediate
        else "Subscription canceled immediately",
    }


@router.post("/reactivate")
async def reactivate_subscription(
    token: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    billing_service = _require_billing_service()

    user = get_user_from_token(token, db)
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()

    if not sub or not sub.stripe_subscription_id:
        raise BadRequestError("No subscription found", code="no_subscription")

    if not sub.cancel_at_period_end:
        return {"status": "already_active", "message": "Subscription is already active"}

    success = billing_service.reactivate_subscription(sub.stripe_subscription_id)

    if not success:
        raise ServiceUnavailableError(
            "Failed to reactivate subscription", code="subscription_reactivate_failed"
        )

    sub.cancel_at_period_end = False
    db.commit()

    write_audit_log(
        db,
        action="billing.subscription.reactivated",
        user_id=user.id,
        resource_type="subscription",
        resource_id=sub.stripe_subscription_id,
    )

    return {"status": "reactivated", "message": "Subscription reactivated"}


@router.get("/invoices")
async def list_invoices(
    limit: int = Query(10, ge=1, le=100),
    token: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    billing_service = _require_billing_service()

    user = get_user_from_token(token, db)
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()

    if not sub or not sub.stripe_customer_id:
        return []

    invoices = billing_service.get_invoices(sub.stripe_customer_id, limit)
    return invoices


@router.get("/usage")
async def get_usage(
    token: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    user = get_user_from_token(token, db)
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    tier = sub.tier if sub else "free"

    server_count = db.query(SSHServer).filter(SSHServer.user_id == user.id).count()
    instance_count = (
        db.query(InstanceModel).filter(InstanceModel.user_id == user.id).count()
    )

    limits = TIER_CONFIGS.get(tier, TIER_CONFIGS["free"])["limits"]

    if billing_module.billing_service:
        limit_check = billing_module.billing_service.check_usage_limits(
            user.id, tier, {"max_servers": server_count, "max_instances": instance_count}
        )
    else:
        limit_check = {"within_limits": True, "violations": []}

    return {
        "tier": tier,
        "usage": {
            "servers": {
                "current": server_count,
                "limit": limits["max_servers"],
                "unlimited": limits["max_servers"] == -1,
            },
            "instances": {
                "current": instance_count,
                "limit": limits["max_instances"],
                "unlimited": limits["max_instances"] == -1,
            },
        },
        "period": {
            "start": datetime.utcnow().replace(day=1).isoformat(),
            "end": (datetime.utcnow().replace(day=1) + timedelta(days=30)).isoformat(),
        },
        "within_limits": limit_check.get("within_limits", True),
        "violations": limit_check.get("violations", []),
    }


@router.post("/nowpayments/checkout")
async def nowpayments_checkout(
    checkout: CheckoutRequest,
    token: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    nowpayments_service = _require_nowpayments_service()

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
    result = await nowpayments_service.create_payment(
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
        action="billing.nowpayments.checkout.created",
        user_id=user.id,
        resource_type="payment",
        resource_id=result.get("payment_id"),
        details={
            "tier": checkout.tier,
            "billing_period": checkout.billing_period,
            "amount_cents": amount_cents,
        },
    )

    return result


@router.post("/nowpayments/webhook")
async def nowpayments_webhook(request: Request, db: Session = Depends(get_db)):
    nowpayments_service = _require_nowpayments_service()

    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise BadRequestError("Malformed webhook payload", code="malformed_payload")

    signature = request.headers.get("x-nowpayments-sig", "")

    if not nowpayments_service.verify_webhook(raw, signature):
        raise BadRequestError("Invalid IPN signature", code="invalid_ipn_signature")

    payment_status = payload.get("payment_status")
    order_id = payload.get("order_id", "")

    if payment_status == "finished":
        # order_id format: {user_id}_{tier}_{billing_period}
        parts = order_id.split("_", 2)
        if len(parts) == 3:
            user_id, tier, billing_period = int(parts[0]), parts[1], parts[2]
            payment_id = payload.get("payment_id")

            # Idempotency: a provider may deliver the same webhook more than
            # once (retries, redeliveries). If this payment already activated
            # the subscription, acknowledge without re-activating.
            if _activation_audit_exists(db, user_id, payment_id):
                logger.info(
                    f"NOWPayments: duplicate webhook for payment {payment_id} "
                    f"of user {user_id}, skipping"
                )
                return {"status": "ok"}

            # Amount validation: reject underpaid/fraudulent webhooks before
            # granting access. Only enforced when the tier/period price is
            # known and the payload carries a parseable paid amount.
            expected_cents = _expected_amount_cents(tier, billing_period)
            paid_cents = _parse_paid_amount_cents(payload)
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
                        "payment_status": payment_status,
                    },
                )
                logger.error(
                    f"NOWPayments: amount mismatch for payment {payment_id} "
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
                # A concurrent webhook delivery for the same user may have
                # already created the subscription (user_id is unique); the
                # activation was effectively processed, so acknowledge.
                db.rollback()
                logger.warning(
                    f"NOWPayments: concurrent activation for user {user_id}, "
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
            logger.info(
                f"NOWPayments: activated {tier} subscription for user {user_id}"
            )
        else:
            logger.error(f"NOWPayments: invalid order_id format: {order_id}")

    elif payment_status in ("failed", "expired"):
        logger.error(f"NOWPayments: payment {payment_status} for order {order_id}")

    return {"status": "ok"}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not billing_module.billing_service:
        return {"status": "error", "message": "Billing not configured"}

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        return {"status": "error", "message": "Missing signature"}

    result = billing_module.billing_service.handle_webhook(payload, sig_header, db)

    if result.get("status") == "processed":
        event_type = result.get("type")
        logger.info(f"Processed webhook event: {event_type}")

    return result
