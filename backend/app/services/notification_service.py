import hashlib
import hmac
import html
import httpx
import ipaddress
import json
import logging
import socket
from datetime import datetime
from typing import Dict, Any, List
from urllib.parse import urlparse

from app.core.database import SessionLocal
from app.models.database import WebhookConfig as DBWebhookConfig
from app.services.encryption import encryption_service

logger = logging.getLogger(__name__)


def validate_webhook_url(url: str) -> None:
    """Reject webhook targets that could enable SSRF.

    Allows only http/https URLs whose resolved addresses are public.
    Blocks loopback, private, link-local (incl. the 169.254.169.254
    cloud-metadata address) and unspecified IPs. Raises ValueError with
    a generic message when the URL is not safe to fetch.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https webhook URLs are allowed")
    host = parsed.hostname
    if not host:
        raise ValueError("Webhook URL must include a host")
    if host.lower().strip("[]") in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ValueError("Webhook URL host is not allowed")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except Exception:
        raise ValueError("Webhook URL host could not be resolved")

    for address in addresses:
        ip_str = address[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise ValueError("Webhook URL resolves to a blocked address")


class NotificationService:
    def __init__(self):
        self.telegram_token = None
        self.telegram_chat_id = None
        self.webhook_urls = {}

    def configure_telegram(self, token: str, chat_id: str):
        self.telegram_token = token
        self.telegram_chat_id = chat_id

    def add_webhook(self, name: str, url: str, events: List[str]):
        validate_webhook_url(url)
        self.webhook_urls[name] = {"url": url, "events": events, "active": True}

    async def send_telegram(self, message: str, parse_mode: str = "HTML") -> bool:
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("Telegram not configured")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def send_webhook(self, event: str, data: Dict[str, Any]) -> bool:
        success = True
        for name, config in self.webhook_urls.items():
            if not config["active"] or event not in config["events"]:
                continue

            payload = {
                "event": event,
                "timestamp": datetime.utcnow().isoformat(),
                "data": data,
            }

            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(config["url"], json=payload, timeout=10)
                    if resp.status_code >= 400:
                        logger.error(f"Webhook {name} failed: {resp.status_code}")
                        success = False
            except Exception as e:
                logger.error(f"Webhook {name} error: {e}")
                success = False

        # Runtime webhook configs from the database (B17)
        db = SessionLocal()
        try:
            webhooks = (
                db.query(DBWebhookConfig)
                .filter(DBWebhookConfig.is_active.is_(True))
                .all()
            )
            for webhook in webhooks:
                try:
                    events = json.loads(webhook.events) if webhook.events else []
                except Exception as e:
                    logger.error(f"Webhook {webhook.name} events parse error: {e}")
                    success = False
                    continue
                if event not in events:
                    continue
                try:
                    validate_webhook_url(webhook.url)
                except ValueError as e:
                    logger.error(f"Webhook {webhook.name} skipped: {e}")
                    success = False
                    continue

                payload = {
                    "event": event,
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": data,
                }
                headers = {"Content-Type": "application/json"}
                try:
                    if webhook.secret:
                        secret = encryption_service.decrypt(webhook.secret)
                        signature = hmac.new(
                            secret.encode(),
                            json.dumps(payload).encode(),
                            hashlib.sha256,
                        ).hexdigest()
                        headers["X-Signature"] = signature
                except Exception as e:
                    logger.error(f"Webhook {webhook.name} secret error: {e}")
                    success = False
                    continue

                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.post(
                            webhook.url, json=payload, headers=headers, timeout=10
                        )
                        if resp.status_code >= 400:
                            logger.error(
                                f"Webhook {webhook.name} failed: {resp.status_code}"
                            )
                            success = False
                except Exception as e:
                    logger.error(f"Webhook {webhook.name} error: {e}")
                    success = False
        finally:
            db.close()

        return success

    async def notify(
        self, event: str, data: Dict[str, Any], channels: List[str] = None
    ) -> Dict[str, bool]:
        results = {}
        message = self._format_message(event, data)

        if channels is None or "telegram" in channels:
            results["telegram"] = await self.send_telegram(message)

        if channels is None or "webhook" in channels:
            results["webhook"] = await self.send_webhook(event, data)

        return results

    def _format_message(self, event: str, data: Dict[str, Any]) -> str:
        def esc(value):
            return html.escape(str(value)) if value is not None else ""

        if event == "order_executed":
            return (
                f"📊 <b>Order Executed</b>\n"
                f"Symbol: {esc(data.get('symbol'))}\n"
                f"Type: {esc(data.get('order_type'))}\n"
                f"Volume: {esc(data.get('volume'))}\n"
                f"Price: {esc(data.get('price'))}\n"
                f"Ticket: {esc(data.get('ticket'))}"
            )
        elif event == "position_closed":
            pnl = data.get("profit", 0)
            emoji = "✅" if pnl >= 0 else "❌"
            return (
                f"{emoji} <b>Position Closed</b>\n"
                f"Symbol: {esc(data.get('symbol'))}\n"
                f"P&L: ${pnl:.2f}\n"
                f"Ticket: {esc(data.get('ticket'))}"
            )
        elif event == "price_alert":
            return (
                f"🔔 <b>Price Alert</b>\n"
                f"Symbol: {esc(data.get('symbol'))}\n"
                f"Condition: {esc(data.get('condition'))}\n"
                f"Current Price: {esc(data.get('price'))}"
            )
        elif event == "margin_call":
            return (
                f"⚠️ <b>MARGIN WARNING</b>\n"
                f"Account: {esc(data.get('account'))}\n"
                f"Margin Level: {esc(data.get('margin_level'))}%\n"
                f"Free Margin: ${data.get('free_margin', 0):.2f}"
            )
        elif event == "instance_status":
            return (
                f"🖥️ <b>Instance {esc(data.get('status'))}</b>\n"
                f"Name: {esc(data.get('name'))}\n"
                f"ID: {esc(data.get('id'))}"
            )
        else:
            return f"📢 <b>{html.escape(event)}</b>\n{json.dumps(data, indent=2)}"


notification_service = NotificationService()
