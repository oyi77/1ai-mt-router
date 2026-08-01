from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List, Literal
from pydantic import BaseModel
from datetime import datetime

from app.auth.jwt import get_current_user_or_api_key
from app.services.notification_service import notification_service
from app.services.alert_engine import alert_engine, AlertRule, AlertType, AlertCondition

router = APIRouter()


class TelegramConfig(BaseModel):
    bot_token: str
    chat_id: str


class WebhookConfig(BaseModel):
    name: str
    url: str
    events: List[str]


class AlertRuleCreate(BaseModel):
    alert_type: AlertType
    symbol: Optional[str]
    condition: AlertCondition
    value: float
    channel: Literal["telegram", "webhook"] = "telegram"
    cooldown_seconds: int = 300


class AlertRuleResponse(BaseModel):
    id: str
    alert_type: str
    symbol: Optional[str]
    condition: str
    value: float
    channel: str
    is_active: bool
    last_triggered: Optional[datetime]


@router.post("/telegram/configure")
async def configure_telegram(config: TelegramConfig, user=Depends(get_current_user_or_api_key)):
    notification_service.configure_telegram(config.bot_token, config.chat_id)
    return {"status": "configured", "message": "Telegram bot configured successfully"}


@router.post("/telegram/test")
async def test_telegram(user=Depends(get_current_user_or_api_key)):
    success = await notification_service.send_telegram(
        "🧪 <b>MT5 Router Test</b>\nTelegram notifications are working!"
    )
    return {"success": success}


@router.post("/webhooks")
async def add_webhook(config: WebhookConfig, user=Depends(get_current_user_or_api_key)):
    try:
        notification_service.add_webhook(config.name, config.url, config.events)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "added", "name": config.name}


@router.get("/webhooks")
async def list_webhooks(user=Depends(get_current_user_or_api_key)):
    return notification_service.webhook_urls


@router.delete("/webhooks/{name}")
async def delete_webhook(name: str, user=Depends(get_current_user_or_api_key)):
    if name in notification_service.webhook_urls:
        del notification_service.webhook_urls[name]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Webhook not found")


@router.post("/alerts")
async def create_alert(rule: AlertRuleCreate, user=Depends(get_current_user_or_api_key)):
    import uuid

    alert_id = str(uuid.uuid4())[:8]

    alert_rule = AlertRule(
        id=alert_id,
        user_id=user.id,
        alert_type=rule.alert_type,
        symbol=rule.symbol,
        condition=rule.condition,
        value=rule.value,
        channel=rule.channel,
        is_active=True,
        cooldown_seconds=rule.cooldown_seconds,
    )

    alert_engine.add_rule(alert_rule)

    return {
        "id": alert_id,
        "status": "created",
        "rule": {
            "type": rule.alert_type,
            "symbol": rule.symbol,
            "condition": f"{rule.condition} {rule.value}",
            "channel": rule.channel,
        },
    }


@router.get("/alerts")
async def list_alerts(user=Depends(get_current_user_or_api_key)):
    user_rules = [
        {
            "id": rule_id,
            "type": rule.alert_type.value,
            "symbol": rule.symbol,
            "condition": rule.condition.value,
            "value": rule.value,
            "channel": rule.channel,
            "is_active": rule.is_active,
            "last_triggered": rule.last_triggered,
        }
        for rule_id, rule in alert_engine.rules.items()
        if rule.user_id == user.id
    ]
    return user_rules


@router.put("/alerts/{alert_id}")
async def update_alert(
    alert_id: str, is_active: Optional[bool] = None, user=Depends(get_current_user_or_api_key)
):
    rule = alert_engine.rules.get(alert_id)
    if not rule or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert not found")

    if is_active is not None:
        alert_engine.update_rule(alert_id, is_active=is_active)

    return {"status": "updated"}


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, user=Depends(get_current_user_or_api_key)):
    rule = alert_engine.rules.get(alert_id)
    if not rule or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert_engine.remove_rule(alert_id)
    return {"status": "deleted"}


@router.post("/test")
async def send_test_notification(
    channel: str = "telegram", user=Depends(get_current_user_or_api_key)
):
    results = await notification_service.notify(
        event="test",
        data={"message": "Test notification from MT5 Router"},
        channels=[channel],
    )
    return {"results": results}
