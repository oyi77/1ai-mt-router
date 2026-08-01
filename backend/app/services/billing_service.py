import copy
import json
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

import stripe
from sqlalchemy.orm import Session

from app.config import settings
from app.core.audit import write_audit_log
from app.models.database import Invoice, Subscription

logger = logging.getLogger(__name__)

_DEFAULT_TIER_CONFIGS = {
    "free": {
        "name": "Free",
        "price_monthly": 0,
        "price_yearly": 0,
        "limits": {
            "max_servers": 1,
            "max_instances": 1,
            "max_api_calls_per_day": 1000,
            "max_users": 1,
            "support_level": "community",
        },
        "features": [
            "1 MT5 instance",
            "Basic monitoring",
            "Community support",
            "1,000 API calls/day",
        ],
    },
    "basic": {
        "name": "Basic",
        "price_monthly": 2900,
        "price_yearly": 29000,
        "limits": {
            "max_servers": 3,
            "max_instances": 5,
            "max_api_calls_per_day": 10000,
            "max_users": 3,
            "support_level": "email",
        },
        "features": [
            "5 MT5 instances",
            "3 servers",
            "Telegram alerts",
            "Email support",
            "10,000 API calls/day",
        ],
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 7900,
        "price_yearly": 79000,
        "limits": {
            "max_servers": 10,
            "max_instances": 25,
            "max_api_calls_per_day": 100000,
            "max_users": 10,
            "support_level": "priority",
        },
        "features": [
            "25 MT5 instances",
            "10 servers",
            "Copy trading API",
            "Priority support",
            "Webhook integration",
            "100,000 API calls/day",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "price_monthly": 0,
        "price_yearly": 0,
        "limits": {
            "max_servers": -1,
            "max_instances": -1,
            "max_api_calls_per_day": -1,
            "max_users": -1,
            "support_level": "dedicated",
        },
        "features": [
            "Unlimited instances",
            "Unlimited servers",
            "Dedicated support",
            "Custom integrations",
            "SLA guarantee",
            "White-label option",
        ],
    },
}

_TIERS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "tiers.json",
)


def _load_tier_configs() -> Dict[str, Any]:
    """Load tier configs from data/tiers.json, falling back to defaults.

    tiers.json is the single source of truth for tier pricing and limits
    (M12); if it is missing or corrupt we log a warning and use the embedded
    defaults so the router still boots.
    """
    try:
        with open(_TIERS_FILE_PATH, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "basic" not in data:
            raise ValueError("tiers.json missing required 'basic' tier")
        return data
    except (OSError, ValueError, json.JSONDecodeError) as e:
        logger.warning(
            f"Failed to load tiers.json ({e}); using default tier configs"
        )
        return copy.deepcopy(_DEFAULT_TIER_CONFIGS)


TIER_CONFIGS = _load_tier_configs()


class BillingService:
    def __init__(self, stripe_secret_key: str, webhook_secret: str):
        stripe.api_key = stripe_secret_key
        self.webhook_secret = webhook_secret

    def create_customer(
        self, email: str, name: str = None, user_id: int = None
    ) -> Optional[str]:
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={"user_id": str(user_id)} if user_id else {},
            )
            return customer.id
        except Exception as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            return None

    def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int = 14,
        tier: str = None,
        billing_period: str = None,
        user_id: int = None,
    ) -> Optional[Dict]:
        try:
            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                subscription_data={
                    "trial_period_days": trial_days,
                    "metadata": {
                        "user_id": str(user_id),
                        "tier": tier,
                        "billing_period": billing_period,
                    },
                },
            )
            return {"session_id": session.id, "url": session.url}
        except Exception as e:
            logger.error(f"Failed to create checkout session: {e}")
            return None

    def create_customer_portal_session(
        self, customer_id: str, return_url: str
    ) -> Optional[str]:
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id, return_url=return_url
            )
            return session.url
        except Exception as e:
            logger.error(f"Failed to create portal session: {e}")
            return None

    def cancel_subscription(
        self, subscription_id: str, cancel_at_period_end: bool = True
    ) -> bool:
        try:
            if cancel_at_period_end:
                stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
            else:
                stripe.Subscription.delete(subscription_id)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {e}")
            return False

    def reactivate_subscription(self, subscription_id: str) -> bool:
        try:
            stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)
            return True
        except Exception as e:
            logger.error(f"Failed to reactivate subscription: {e}")
            return False

    def get_subscription(self, subscription_id: str) -> Optional[Dict]:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            return {
                "id": sub.id,
                "status": sub.status,
                "current_period_start": datetime.fromtimestamp(
                    sub.current_period_start
                ),
                "current_period_end": datetime.fromtimestamp(sub.current_period_end),
                "cancel_at_period_end": sub.cancel_at_period_end,
                "items": [
                    {"price_id": item.price.id, "quantity": item.quantity}
                    for item in sub.items.data
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get subscription: {e}")
            return None

    def get_invoices(self, customer_id: str, limit: int = 10) -> List[Dict]:
        try:
            invoices = stripe.Invoice.list(customer=customer_id, limit=limit)
            return [
                {
                    "id": inv.id,
                    "amount": inv.amount_paid,
                    "currency": inv.currency,
                    "status": inv.status,
                    "invoice_url": inv.hosted_invoice_url,
                    "pdf_url": inv.invoice_pdf,
                    "created": datetime.fromtimestamp(inv.created),
                    "period_start": datetime.fromtimestamp(inv.period_start)
                    if inv.period_start
                    else None,
                    "period_end": datetime.fromtimestamp(inv.period_end)
                    if inv.period_end
                    else None,
                }
                for inv in invoices.data
            ]
        except Exception as e:
            logger.error(f"Failed to get invoices: {e}")
            return []

    def record_usage(
        self, subscription_item_id: str, quantity: int, timestamp: int = None
    ) -> bool:
        try:
            stripe.UsageRecord.create(
                subscription_item_id=subscription_item_id,
                quantity=quantity,
                timestamp=timestamp or int(datetime.utcnow().timestamp()),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to record usage: {e}")
            return False

    def handle_webhook(
        self, payload: bytes, sig_header: str, db: Session
    ) -> Dict[str, Any]:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )

            handler_map = {
                "checkout.session.completed": self._handle_checkout_completed,
                "customer.subscription.created": self._handle_subscription_created,
                "customer.subscription.updated": self._handle_subscription_updated,
                "customer.subscription.deleted": self._handle_subscription_deleted,
                "invoice.paid": self._handle_invoice_paid,
                "invoice.payment_failed": self._handle_invoice_failed,
            }

            handler = handler_map.get(event["type"])
            if handler:
                return handler(db, event["data"]["object"])

            return {"status": "unhandled", "type": event["type"]}

        except stripe.error.SignatureVerificationError:
            return {"status": "error", "message": "Invalid signature"}
        except Exception:
            logger.error("Webhook error", exc_info=True)
            return {"status": "error", "message": "Webhook processing failed"}

    def _handle_checkout_completed(
        self, db: Session, session: Dict
    ) -> Dict:
        user_id = None
        metadata = session.get("metadata") or {}
        if metadata.get("user_id"):
            try:
                user_id = int(metadata["user_id"])
            except (TypeError, ValueError):
                user_id = None

        if user_id is None:
            user_id = self._resolve_user_id(db, session.get("customer"))

        if user_id is None:
            sub = (
                db.query(Subscription)
                .filter(
                    Subscription.stripe_subscription_id == session.get("subscription")
                )
                .first()
            )
            user_id = sub.user_id if sub else None

        if user_id is None:
            logger.error(
                f"Checkout {session.get('id')}: no user for checkout, skipping"
            )
            return {"status": "error", "message": "No user for checkout"}

        tier = metadata.get("tier") or "free"
        self._upsert_subscription(
            db,
            {
                "id": session.get("subscription"),
                "customer": session.get("customer"),
                "status": "active",
            },
            user_id=user_id,
            tier=tier,
        )

        if session.get("invoice"):
            self._upsert_invoice(db, user_id, {"id": session.get("invoice")})

        write_audit_log(
            db,
            action="stripe.checkout.completed",
            user_id=user_id,
            resource_type="checkout",
            resource_id=session.get("id"),
            details={
                "tier": tier,
                "billing_period": metadata.get("billing_period"),
            },
        )
        return {"status": "processed", "type": "checkout.completed"}

    def _handle_subscription_created(
        self, db: Session, subscription: Dict
    ) -> Dict:
        sub = self._upsert_subscription(db, subscription)
        write_audit_log(
            db,
            action="stripe.subscription.created",
            user_id=sub.user_id if sub else None,
            resource_type="subscription",
            resource_id=subscription.get("id"),
        )
        return {"status": "processed", "type": "subscription.created"}

    def _handle_subscription_updated(
        self, db: Session, subscription: Dict
    ) -> Dict:
        sub = self._upsert_subscription(db, subscription)
        write_audit_log(
            db,
            action="stripe.subscription.updated",
            user_id=sub.user_id if sub else None,
            resource_type="subscription",
            resource_id=subscription.get("id"),
        )
        return {"status": "processed", "type": "subscription.updated"}

    def _handle_subscription_deleted(
        self, db: Session, subscription: Dict
    ) -> Dict:
        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == subscription.get("id"))
            .first()
        )
        if sub:
            sub.status = "canceled"
            sub.cancel_at_period_end = True
            db.commit()
        write_audit_log(
            db,
            action="stripe.subscription.deleted",
            user_id=sub.user_id if sub else None,
            resource_type="subscription",
            resource_id=subscription.get("id"),
        )
        return {"status": "processed", "type": "subscription.deleted"}

    def _handle_invoice_paid(self, db: Session, invoice: Dict) -> Dict:
        user_id = self._resolve_user_id(db, invoice.get("customer"))
        if user_id is None:
            logger.warning(
                f"Invoice {invoice.get('id')}: no user for customer, skipping"
            )
            return {"status": "processed", "type": "invoice.paid"}
        self._upsert_invoice(db, user_id, invoice)
        write_audit_log(
            db,
            action="stripe.invoice.paid",
            user_id=user_id,
            resource_type="invoice",
            resource_id=invoice.get("id"),
            details={"amount_cents": invoice.get("amount_paid")},
        )
        return {"status": "processed", "type": "invoice.paid"}

    def _handle_invoice_failed(self, db: Session, invoice: Dict) -> Dict:
        user_id = self._resolve_user_id(db, invoice.get("customer"))
        if user_id is None:
            logger.warning(
                f"Invoice {invoice.get('id')}: no user for customer, skipping"
            )
            return {"status": "processed", "type": "invoice.payment_failed"}
        self._upsert_invoice(db, user_id, invoice)
        write_audit_log(
            db,
            action="stripe.invoice.payment_failed",
            user_id=user_id,
            resource_type="invoice",
            resource_id=invoice.get("id"),
        )
        return {"status": "processed", "type": "invoice.payment_failed"}

    def _resolve_tier_from_price(self, price_id: str) -> Optional[str]:
        """Map a configured Stripe price id back to its tier name."""
        if not price_id:
            return None
        for name, config in TIER_CONFIGS.items():
            for period in ("monthly", "yearly"):
                configured = getattr(
                    settings, f"STRIPE_PRICE_{name.upper()}_{period.upper()}", ""
                )
                if configured and configured == price_id:
                    return name
        return None

    def _resolve_user_id(self, db: Session, customer_id: str) -> Optional[int]:
        """Find the internal user id for a Stripe customer, if known."""
        if not customer_id:
            return None
        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_customer_id == customer_id)
            .first()
        )
        return sub.user_id if sub else None

    def _upsert_invoice(
        self, db: Session, user_id: int, invoice: Dict
    ) -> Optional[Invoice]:
        """Create or update an Invoice row from a Stripe invoice object."""
        inv_id = invoice.get("id")
        if not inv_id:
            return None

        amount = invoice.get("amount_paid") or invoice.get("amount_due") or 0

        def _ts(value):
            if isinstance(value, (int, float)):
                return datetime.utcfromtimestamp(value)
            return None

        inv = (
            db.query(Invoice)
            .filter(Invoice.stripe_invoice_id == inv_id)
            .first()
        )
        if not inv:
            inv = Invoice(
                user_id=user_id,
                stripe_invoice_id=inv_id,
                amount_cents=amount,
                currency=invoice.get("currency") or "usd",
                status=invoice.get("status") or "pending",
                invoice_url=invoice.get("hosted_invoice_url"),
                pdf_url=invoice.get("invoice_pdf"),
                period_start=_ts(invoice.get("period_start")),
                period_end=_ts(invoice.get("period_end")),
            )
            db.add(inv)
        else:
            inv.user_id = user_id
            inv.amount_cents = amount
            inv.status = invoice.get("status") or inv.status
            inv.invoice_url = invoice.get("hosted_invoice_url") or inv.invoice_url
            inv.pdf_url = invoice.get("invoice_pdf") or inv.invoice_pdf

        db.commit()
        return inv

    def _upsert_subscription(
        self,
        db: Session,
        subscription: Dict,
        user_id: int = None,
        tier: str = None,
    ) -> Optional[Subscription]:
        """Create or update a Subscription row from a Stripe object."""
        sub_id = subscription.get("id")
        customer_id = subscription.get("customer")
        if user_id is None:
            user_id = self._resolve_user_id(db, customer_id)
        if not sub_id or user_id is None:
            logger.warning(
                f"Subscription {sub_id}: missing id or no user, skipping upsert"
            )
            return None

        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == sub_id)
            .first()
        )

        if tier is None:
            items = subscription.get("items") or []
            price_id = items[0].get("price", {}).get("id") if items else None
            tier = self._resolve_tier_from_price(price_id)
        if tier is None:
            tier = "free"

        def _ts(value):
            if isinstance(value, (int, float)):
                return datetime.utcfromtimestamp(value)
            return None

        period_start = _ts(subscription.get("current_period_start"))
        period_end = _ts(subscription.get("current_period_end"))

        if not sub:
            sub = Subscription(
                user_id=user_id,
                stripe_subscription_id=sub_id,
                stripe_customer_id=customer_id,
                tier=tier,
                status=subscription.get("status") or "active",
                current_period_start=period_start,
                current_period_end=period_end,
            )
            db.add(sub)
        else:
            sub.user_id = user_id
            sub.stripe_customer_id = customer_id or sub.stripe_customer_id
            sub.tier = tier
            sub.status = subscription.get("status") or sub.status
            sub.current_period_start = period_start or sub.current_period_start
            sub.current_period_end = period_end or sub.current_period_end
            if "cancel_at_period_end" in subscription:
                sub.cancel_at_period_end = bool(
                    subscription["cancel_at_period_end"]
                )
            else:
                sub.cancel_at_period_end = False

        db.commit()
        return sub

    def check_usage_limits(
        self, user_id: int, tier: str, current_usage: Dict[str, int]
    ) -> Dict[str, Any]:
        limits = TIER_CONFIGS.get(tier, TIER_CONFIGS["free"])["limits"]

        violations = []
        for metric, limit in limits.items():
            if limit == -1:
                continue
            current = current_usage.get(metric, 0)
            if current >= limit:
                violations.append(
                    {"metric": metric, "limit": limit, "current": current}
                )

        return {
            "within_limits": len(violations) == 0,
            "violations": violations,
            "tier": tier,
            "limits": limits,
        }

    def get_tier_config(self, tier: str) -> Dict[str, Any]:
        return TIER_CONFIGS.get(tier, TIER_CONFIGS["free"])


billing_service: Optional[BillingService] = None


def init_billing_service(stripe_secret_key: str, webhook_secret: str):
    global billing_service
    billing_service = BillingService(stripe_secret_key, webhook_secret)
    return billing_service
