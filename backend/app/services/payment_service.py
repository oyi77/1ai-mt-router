"""1ai-payment aggregator integration.

1ai-payment is a self-hosted payment aggregator that fronts multiple gateways
(Stripe, NOWPayments, ...) behind a single API. This module talks to it on
behalf of MT5 Router, mirroring the NOWPayments integration in ``app.api.billing``
while honouring the aggregator's own contract:

- amounts are reported in the smallest currency unit (integer cents),
- ``order_id`` is an opaque aggregator id (nanoid), with the subscription
  context carried separately in ``project_order_id``,
- webhooks are labelled with ``X-Payment-Event`` and signed with HMAC-SHA256
  over the raw body (``X-Payment-Signature``).

The module-level ``payment_service`` global is bound at startup by
``init_payment_service``; consumers must read the module attribute at call time
because a direct import freezes it at ``None``.
"""
import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class PaymentService:
    """Thin client for the 1ai-payment aggregator HTTP API."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        gateway: str,
        webhook_secret: str = "",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.gateway = gateway
        self.webhook_secret = webhook_secret

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    async def create_payment(
        self,
        amount_cents: int,
        tier: str,
        billing_period: str,
        user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Create an aggregator payment and return payment_url + payment_id."""
        payload = {
            # ``gateway`` must match a gateway id configured in the aggregator
            # (its API rejects unknown gateways with 401/400).
            "gateway": self.gateway,
            "amount": int(amount_cents),
            "currency": "usd",
            "callback_url": f"{settings.BASE_URL}/api/v1/payments/webhook",
            "idempotency_key": f"mtr-{user_id}-{tier}-{billing_period}",
            # Subscription context for the webhook: {user_id}_{tier}_{period}.
            "project_order_id": f"{user_id}_{tier}_{billing_period}",
            "metadata": {
                "user_id": user_id,
                "tier": tier,
                "billing_period": billing_period,
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/api/payments",
                    headers=self._headers(),
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "payment_url": data["data"]["payment_url"],
                    "payment_id": data["data"]["id"],
                    "gateway": self.gateway,
                }
        except Exception as e:
            logger.error(f"1ai-payment create_payment failed: {e}")
            return None

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify an aggregator webhook signature using HMAC-SHA256.

        When no webhook secret is configured (e.g. a local aggregator without
        signature support), validation is skipped so the flow stays testable.
        """
        if not self.webhook_secret:
            return True
        if not signature:
            return False

        computed = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed, signature)


payment_service: Optional[PaymentService] = None


def init_payment_service(
    api_key: str,
    base_url: str,
    gateway: str,
    webhook_secret: str = "",
) -> PaymentService:
    global payment_service
    payment_service = PaymentService(api_key, base_url, gateway, webhook_secret)
    return payment_service
