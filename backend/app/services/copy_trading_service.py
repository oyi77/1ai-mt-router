"""Copy-trading execution service (F4).

Consumes pending ``CopySignal`` rows and places matching orders on each
subscriber's target MT5 account through ``MT5Service.place_order``.

Scheduling note: there is no signal-creation endpoint in the API yet, so this
module deliberately does not install its own cron/background loop. To execute
signals on a schedule, call :func:`dispatch_signals` from an external scheduler
or background task with its own SQLAlchemy session (e.g. every N seconds):

    def _run():
        from app.core.database import SessionLocal
        from app.services.copy_trading_service import dispatch_signals
        db = SessionLocal()
        try:
            dispatch_signals(db)
        finally:
            db.close()
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.database import (
    CopyPosition,
    CopySignal,
    CopyStrategy,
)
from app.services.mt5_service import MT5Service

logger = logging.getLogger(__name__)

# Per-subscriber outcome keys used in the result dicts.
_EXECUTED = "executed"


def calculate_lot_size(
    signal_volume: Optional[float],
    multiplier: float,
    lot_type: str,
    balance: Optional[float] = None,
) -> Optional[float]:
    """Compute the lot volume for one subscriber.

    ``lot_type`` "fixed": ``signal_volume * multiplier``.
    ``lot_type`` "percentage": ``balance * multiplier / 100`` (literal
    percent of the account balance expressed in lots).

    Returns ``None`` when the input cannot produce a volume: no/invalid
    signal volume, an out-of-range multiplier (must be 0 < m <= 100), or a
    percentage calculation without an available balance.
    """
    if signal_volume is None or signal_volume <= 0:
        return None
    if multiplier is None or multiplier <= 0 or multiplier > 100:
        return None

    if lot_type == "fixed":
        return round(signal_volume * multiplier, 2)

    if lot_type == "percentage":
        if balance is None:
            return None
        return round(balance * multiplier / 100, 2)

    raise ValueError(f"Unknown lot_type: {lot_type!r}")


def _get_balance(account, mt5_cls) -> Optional[float]:
    """Return the account balance from the MT5 gateway, or None if unavailable.

    The ``MT5Account`` model has no balance column; the balance is read from
    ``get_account_info()``. Never fabricate a balance: ``None`` is returned
    when the info is missing or unparseable, and callers skip the subscriber.
    """
    try:
        info = mt5_cls(account.instance_id).get_account_info()
    except Exception as exc:
        logger.error("get_account_info failed for %s: %s", account.instance_id, exc)
        return None
    if not info or info.get("balance") is None:
        return None
    try:
        return float(info["balance"])
    except (TypeError, ValueError):
        logger.error("Unparseable balance for %s: %r", account.instance_id, info.get("balance"))
        return None


def process_signal(db: Session, signal: CopySignal, mt5_cls=None) -> Dict:
    """Execute one signal across its strategy's active subscribers.

    ``mt5_cls`` defaults to the module-level ``MT5Service`` and is injectable
    for tests. Failures are isolated per subscriber: one subscriber's error
    never aborts the others, and each successful order is committed
    immediately so the ``CopyPosition`` guard stays durable even if a later
    subscriber dies. The signal status is finalized as one of
    executed/partial/failed/skipped. Never raises.
    """
    mt5_cls = mt5_cls or MT5Service
    outcomes: List[Dict] = []
    errors: List[str] = []
    placed = 0
    failed = 0

    strategy = signal.strategy
    if strategy is None:
        signal.status = "failed"
        signal.error_message = "strategy not found"
        db.commit()
        return {"signal_id": signal.id, "status": signal.status, "subscribers": outcomes}

    if not strategy.is_active:
        signal.status = "skipped"
        signal.error_message = None
        db.commit()
        return {"signal_id": signal.id, "status": signal.status, "subscribers": outcomes}

    active_subs = [s for s in strategy.subscribers if s.is_active]
    if not active_subs:
        signal.status = "skipped"
        signal.error_message = None
        db.commit()
        return {"signal_id": signal.id, "status": signal.status, "subscribers": outcomes}

    for sub in active_subs:
        try:
            existing = (
                db.query(CopyPosition)
                .filter(
                    CopyPosition.subscriber_id == sub.id,
                    CopyPosition.provider_ticket == signal.ticket,
                )
                .first()
            )
            if existing:
                outcomes.append(
                    {"subscriber_id": sub.id, "status": "already_executed", "error": None}
                )
                continue

            account = sub.target_account
            if account is None or not account.instance_id:
                outcomes.append(
                    {"subscriber_id": sub.id, "status": "no_instance", "error": None}
                )
                failed += 1
                errors.append(f"subscriber {sub.id}: no target instance")
                continue

            balance = None
            if sub.lot_type == "percentage":
                balance = _get_balance(account, mt5_cls)
                if balance is None:
                    outcomes.append(
                        {
                            "subscriber_id": sub.id,
                            "status": "balance_unavailable",
                            "error": None,
                        }
                    )
                    failed += 1
                    errors.append(f"subscriber {sub.id}: balance unavailable")
                    continue

            volume = calculate_lot_size(
                signal.volume, sub.lot_multiplier, sub.lot_type, balance
            )
            if volume is None or volume <= 0:
                outcomes.append(
                    {"subscriber_id": sub.id, "status": "invalid_volume", "error": None}
                )
                failed += 1
                errors.append(f"subscriber {sub.id}: invalid volume")
                continue

            max_lots = strategy.max_lots or 1.0
            if volume > max_lots:
                volume = round(max_lots, 2)

            mt5 = mt5_cls(account.instance_id)
            result = mt5.place_order(
                symbol=signal.symbol,
                order_type=signal.order_type,
                volume=volume,
                price=signal.price,
                sl=signal.sl,
                tp=signal.tp,
            )
            if not result:
                outcomes.append(
                    {
                        "subscriber_id": sub.id,
                        "status": "place_order_failed",
                        "error": "place_order returned no result",
                    }
                )
                failed += 1
                errors.append(f"subscriber {sub.id}: place_order returned no result")
                continue

            db.add(
                CopyPosition(
                    subscriber_id=sub.id,
                    provider_ticket=signal.ticket,
                    subscriber_ticket=result.get("ticket"),
                    symbol=signal.symbol,
                    order_type=signal.order_type,
                    volume=volume,
                    opened_at=datetime.utcnow(),
                )
            )
            db.commit()
            placed += 1
            outcomes.append(
                {
                    "subscriber_id": sub.id,
                    "status": _EXECUTED,
                    "ticket": result.get("ticket"),
                    "volume": volume,
                }
            )
        except Exception as exc:  # failure isolation per subscriber
            db.rollback()
            logger.exception("Subscriber %s failed while processing signal %s", sub.id, signal.id)
            failed += 1
            errors.append(f"subscriber {sub.id}: {exc}")
            outcomes.append(
                {"subscriber_id": sub.id, "status": "error", "error": str(exc)}
            )

    if placed > 0 and failed == 0:
        signal.status = "executed"
    elif placed > 0:
        signal.status = "partial"
    elif failed > 0:
        signal.status = "failed"
    else:
        signal.status = "skipped"
    signal.error_message = "; ".join(errors) if failed else None

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to finalize signal %s status", signal.id)

    return {"signal_id": signal.id, "status": signal.status, "subscribers": outcomes}


def dispatch_signals(db: Session, user_id: Optional[int] = None) -> List[Dict]:
    """Execute every pending signal (optionally scoped to one user).

    Returns one result dict per processed signal. Signals are marked
    consumed (status ``pending`` -> executed/partial/failed/skipped) so a
    repeated dispatch is a no-op.
    """
    query = db.query(CopySignal).filter(CopySignal.status == "pending")
    if user_id is not None:
        query = query.join(CopyStrategy).filter(CopyStrategy.user_id == user_id)
    signals = query.all()
    return [process_signal(db, signal) for signal in signals]
