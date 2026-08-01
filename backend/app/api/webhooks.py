from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import hmac
import hashlib
import json

from app.auth.jwt import get_current_user
from app.config import settings
from app.core.audit import log_user_action
from app.core.database import get_db
from app.models.database import User, WebhookConfig as DBWebhookConfig
from app.services.encryption import encryption_service
from app.services.notification_service import validate_webhook_url

router = APIRouter()
logger = logging.getLogger(__name__)


class WebhookConfig(BaseModel):
    id: int
    user_id: int
    name: str
    url: str
    secret: Optional[str]
    events: List[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WebhookCreate(BaseModel):
    name: str
    url: str
    secret: Optional[str] = None
    events: List[str]


class WebhookEvent(BaseModel):
    event_type: str
    payload: dict
    timestamp: datetime = datetime.utcnow()


@router.post("/receive")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    signature = request.headers.get("x-nowpayments-sig", "")
    expected = hmac.new(
        settings.NOWPAYMENTS_IPN_SECRET.encode(), raw, hashlib.sha512
    ).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        logger.warning("Webhook rejected: invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw)
        signal_data = {
            "symbol": payload.get("symbol", payload.get("ticker", "")),
            "action": payload.get("action", payload.get("direction", "")).upper(),
            "volume": float(payload.get("volume", payload.get("qty", 0.01))),
            "price": float(payload.get("price", 0)),
        }
        if not signal_data["symbol"]:
            return {"status": "ignored", "reason": "no symbol"}
        logger.info(
            "Processed signal: symbol=%s action=%s volume=%s price=%s",
            signal_data["symbol"],
            signal_data["action"],
            signal_data["volume"],
            signal_data["price"],
        )
        return {"status": "received", "signal": signal_data}
    except Exception:
        logger.error("Webhook payload error", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid webhook payload")


@router.post("/configure")
async def configure_webhook(
    webhook: WebhookCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id
    try:
        validate_webhook_url(webhook.url)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook URL")

    webhook_config = DBWebhookConfig(
        user_id=user_id,
        name=webhook.name,
        url=webhook.url,
        secret=encryption_service.encrypt(webhook.secret) if webhook.secret else None,
        events=json.dumps(webhook.events),
        is_active=True,
    )
    db.add(webhook_config)
    db.commit()
    db.refresh(webhook_config)
    log_user_action(
        db,
        user_id=user_id,
        action="webhook.configure",
        resource_type="webhook",
        resource_id=str(webhook_config.id),
        request=request,
    )

    return {"id": webhook_config.id, "status": "created"}


@router.get("")
async def list_webhooks(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    user_id = user.id
    webhooks = (
        db.query(DBWebhookConfig).filter(DBWebhookConfig.user_id == user_id).all()
    )
    return [
        {
            "id": w.id,
            "name": w.name,
            "url": w.url,
            "events": json.loads(w.events) if w.events else [],
            "is_active": w.is_active,
        }
        for w in webhooks
    ]


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    webhook = (
        db.query(DBWebhookConfig)
        .filter(DBWebhookConfig.id == webhook_id, DBWebhookConfig.user_id == user_id)
        .first()
    )

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    db.delete(webhook)
    db.commit()

    return {"status": "deleted"}


@router.post("/test/{webhook_id}")
async def test_webhook(
    webhook_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    webhook = (
        db.query(DBWebhookConfig)
        .filter(
            DBWebhookConfig.id == webhook_id,
            DBWebhookConfig.user_id == user.id,
        )
        .first()
    )

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    try:
        validate_webhook_url(webhook.url)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook URL")

    import httpx

    test_payload = {
        "event": "test",
        "timestamp": datetime.utcnow().isoformat(),
        "message": "Test webhook from MT5 Router",
    }

    try:
        headers = {"Content-Type": "application/json"}
        if webhook.secret:
            secret = encryption_service.decrypt(webhook.secret)
            body = json.dumps(test_payload)
            signature = hmac.new(
                secret.encode(), body.encode(), hashlib.sha256
            ).hexdigest()
            headers["X-Signature"] = signature

        response = httpx.post(
            webhook.url, json=test_payload, headers=headers, timeout=10
        )
        log_user_action(
            db,
            user_id=user.id,
            action="webhook.test",
            resource_type="webhook",
            resource_id=str(webhook_id),
            request=request,
        )
        return {"status": "success", "response_code": response.status_code}
    except Exception:
        logger.error("Webhook test delivery failed", exc_info=True)
        return {"status": "error", "message": "Webhook delivery failed"}
