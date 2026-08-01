import hashlib
import hmac
import logging
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SANDBOX_BASE_URL = "https://api.sandbox.nowpayments.io/v1"
PRODUCTION_BASE_URL = "https://api.nowpayments.io/v1"


class NOWPaymentsService:
    def __init__(self, api_key: str, ipn_secret: str, sandbox: bool = True):
        self.api_key = api_key
        self.ipn_secret = ipn_secret
        self.base_url = SANDBOX_BASE_URL if sandbox else PRODUCTION_BASE_URL

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def create_payment(
        self,
        amount_cents: int,
        tier: str,
        billing_period: str,
        user_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Create a NOWPayments invoice and return payment_url + payment_id."""
        amount_usd = float(Decimal(amount_cents) / Decimal(100))
        payload = {
            "price_amount": amount_usd,
            "price_currency": "usd",
            "pay_currency": "usdttrc20",
            "order_id": f"{user_id}_{tier}_{billing_period}",
            "order_description": f"MT5 Router {tier.capitalize()} - {billing_period}",
            "ipn_callback_url": f"{settings.BASE_URL}/api/v1/billing/nowpayments/webhook",
            "success_url": f"{settings.BASE_URL}/billing/success",
            "cancel_url": f"{settings.BASE_URL}/billing/cancel",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.base_url}/invoice",
                    headers=self._headers(),
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "payment_url": data.get("invoice_url"),
                    "payment_id": data.get("id"),
                }
        except Exception as e:
            logger.error(f"NOWPayments create_payment failed: {e}")
            return None

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Verify IPN webhook signature using HMAC-SHA512."""
        if not signature or not self.ipn_secret:
            return False

        computed = hmac.new(
            self.ipn_secret.encode("utf-8"),
            payload,
            hashlib.sha512,
        ).hexdigest()

        return hmac.compare_digest(computed, signature)

    async def get_payment_status(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """Get payment status from NOWPayments API."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/payment/{payment_id}",
                    headers=self._headers(),
                    timeout=30,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"NOWPayments get_payment_status failed: {e}")
            return None


nowpayments_service: Optional[NOWPaymentsService] = None


def init_nowpayments_service(
    api_key: str, ipn_secret: str, sandbox: bool = True
) -> NOWPaymentsService:
    global nowpayments_service
    nowpayments_service = NOWPaymentsService(api_key, ipn_secret, sandbox)
    return nowpayments_service
