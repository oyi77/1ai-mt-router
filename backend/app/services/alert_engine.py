import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class AlertType(str, Enum):
    PRICE = "price"
    POSITION = "position"
    ACCOUNT = "account"
    SYSTEM = "system"


class AlertCondition(str, Enum):
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    EQUALS = "equals"
    CROSS_ABOVE = "cross_above"
    CROSS_BELOW = "cross_below"
    PERCENT_CHANGE = "percent_change"


@dataclass
class AlertRule:
    id: str
    user_id: int
    alert_type: AlertType
    symbol: Optional[str]
    condition: AlertCondition
    value: float
    channel: str
    is_active: bool
    cooldown_seconds: int = 300
    last_triggered: Optional[datetime] = None

    def should_trigger(
        self, current_value: float, previous_value: float = None
    ) -> bool:
        if not self.is_active:
            return False

        if self.last_triggered:
            elapsed = (datetime.utcnow() - self.last_triggered).total_seconds()
            if elapsed < self.cooldown_seconds:
                return False

        if self.condition == AlertCondition.GREATER_THAN:
            return current_value > self.value
        elif self.condition == AlertCondition.LESS_THAN:
            return current_value < self.value
        elif self.condition == AlertCondition.EQUALS:
            return abs(current_value - self.value) < 0.0001
        elif self.condition == AlertCondition.CROSS_ABOVE:
            return (
                previous_value is not None
                and previous_value <= self.value
                and current_value > self.value
            )
        elif self.condition == AlertCondition.CROSS_BELOW:
            return (
                previous_value is not None
                and previous_value >= self.value
                and current_value < self.value
            )
        elif self.condition == AlertCondition.PERCENT_CHANGE:
            if previous_value and previous_value != 0:
                pct_change = abs(
                    (current_value - previous_value) / previous_value * 100
                )
                return pct_change >= self.value
        return False


class AlertEngine:
    def __init__(self):
        self.rules: Dict[str, AlertRule] = {}
        self.previous_values: Dict[str, float] = {}
        self.running = False
        self._task = None

    def add_rule(self, rule: AlertRule):
        self.rules[rule.id] = rule

    def remove_rule(self, rule_id: str):
        if rule_id in self.rules:
            del self.rules[rule_id]

    def update_rule(self, rule_id: str, **kwargs):
        if rule_id in self.rules:
            for key, value in kwargs.items():
                setattr(self.rules[rule_id], key, value)

    async def check_price_alerts(
        self, symbol: str, bid: float, ask: float, notify_callback
    ) -> List[str]:
        triggered = []
        price = (bid + ask) / 2

        for rule_id, rule in self.rules.items():
            if rule.alert_type != AlertType.PRICE or rule.symbol != symbol:
                continue

            prev = self.previous_values.get(f"{symbol}_{rule_id}")

            if rule.should_trigger(price, prev):
                rule.last_triggered = datetime.utcnow()
                triggered.append(rule_id)

                await notify_callback(
                    event="price_alert",
                    data={
                        "symbol": symbol,
                        "condition": rule.condition,
                        "value": rule.value,
                        "current_price": price,
                        "rule_id": rule_id,
                    },
                    channel=rule.channel,
                )

            self.previous_values[f"{symbol}_{rule_id}"] = price

        return triggered

    async def check_account_alerts(
        self, account_data: Dict[str, Any], notify_callback
    ) -> List[str]:
        triggered = []

        for rule_id, rule in self.rules.items():
            if rule.alert_type != AlertType.ACCOUNT:
                continue

            current_value = account_data.get(rule.symbol)
            if current_value is None:
                continue

            prev = self.previous_values.get(f"account_{rule_id}")

            if rule.should_trigger(current_value, prev):
                rule.last_triggered = datetime.utcnow()
                triggered.append(rule_id)

                await notify_callback(
                    event="account_alert",
                    data={
                        "metric": rule.symbol,
                        "condition": rule.condition,
                        "value": rule.value,
                        "current_value": current_value,
                        "rule_id": rule_id,
                    },
                    channel=rule.channel,
                )

            self.previous_values[f"account_{rule_id}"] = current_value

        return triggered

    async def check_position_alerts(
        self, positions: List[Dict], notify_callback
    ) -> List[str]:
        triggered = []

        total_pnl = sum(p.get("profit", 0) for p in positions)
        position_count = len(positions)

        for rule_id, rule in self.rules.items():
            if rule.alert_type != AlertType.POSITION:
                continue

            current_value = None
            if rule.symbol == "total_pnl":
                current_value = total_pnl
            elif rule.symbol == "position_count":
                current_value = position_count

            if current_value is None:
                continue

            prev = self.previous_values.get(f"position_{rule_id}")

            if rule.should_trigger(current_value, prev):
                rule.last_triggered = datetime.utcnow()
                triggered.append(rule_id)

                await notify_callback(
                    event="position_alert",
                    data={
                        "metric": rule.symbol,
                        "condition": rule.condition,
                        "value": rule.value,
                        "current_value": current_value,
                        "rule_id": rule_id,
                    },
                    channel=rule.channel,
                )

            self.previous_values[f"position_{rule_id}"] = current_value

        return triggered

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


alert_engine = AlertEngine()
