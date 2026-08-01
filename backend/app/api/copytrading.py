from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from sqlalchemy.orm import Session
from datetime import datetime
import asyncio
import logging

from app.core.database import get_db
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    rollback_on_error,
)
from app.models.database import (
    CopyStrategy,
    CopySubscriber,
    CopySignal,
    CopyPosition,
    User,
    MT5Account,
)
from app.auth.jwt import get_current_user
from app.services.copy_trading_service import dispatch_signals

router = APIRouter()
logger = logging.getLogger(__name__)


class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_account_id: int
    symbol_filter: Optional[str] = None
    max_lots: float = 1.0


class StrategyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    source_account_id: int
    is_active: bool
    symbol_filter: Optional[str]
    max_lots: float
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriberCreate(BaseModel):
    strategy_id: int
    target_account_id: int
    lot_multiplier: float = Field(1.0, gt=0, le=100)
    lot_type: Literal["fixed", "percentage"] = "fixed"


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SubscriberResponse(BaseModel):
    id: int
    strategy_id: int
    target_account_id: int
    is_active: bool
    lot_multiplier: float
    lot_type: str
    created_at: datetime

    class Config:
        from_attributes = True


def strategy_to_response(s: CopyStrategy) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "source_account_id": s.source_account_id,
        "is_active": s.is_active,
        "symbol_filter": s.symbol_filter,
        "max_lots": s.max_lots,
        "created_at": s.created_at,
    }


def subscriber_to_response(s: CopySubscriber) -> dict:
    return {
        "id": s.id,
        "strategy_id": s.strategy_id,
        "target_account_id": s.target_account_id,
        "is_active": s.is_active,
        "lot_multiplier": s.lot_multiplier,
        "lot_type": s.lot_type,
        "created_at": s.created_at,
    }


@router.post("/strategies", response_model=StrategyResponse)
async def create_strategy(
    request: StrategyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    source_account = (
        db.query(MT5Account)
        .filter(
            MT5Account.id == request.source_account_id,
            MT5Account.user_id == user_id,
        )
        .first()
    )
    if not source_account:
        raise NotFoundError("Source account not found", code="source_account_not_found")

    strategy = CopyStrategy(
        user_id=user_id,
        name=request.name,
        description=request.description,
        source_account_id=request.source_account_id,
        symbol_filter=request.symbol_filter,
        max_lots=request.max_lots,
    )
    with rollback_on_error(db):
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
    return strategy_to_response(strategy)


@router.get("/strategies", response_model=List[StrategyResponse])
async def list_strategies(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    user_id = user.id
    strategies = db.query(CopyStrategy).filter(CopyStrategy.user_id == user_id).all()
    return [strategy_to_response(s) for s in strategies]


@router.get("/strategies/{id}", response_model=StrategyResponse)
async def get_strategy(
    id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    user_id = user.id
    strategy = (
        db.query(CopyStrategy)
        .filter(CopyStrategy.id == id, CopyStrategy.user_id == user_id)
        .first()
    )
    if not strategy:
        raise NotFoundError("Strategy not found", code="strategy_not_found")
    return strategy_to_response(strategy)


@router.put("/strategies/{id}", response_model=StrategyResponse)
async def update_strategy(
    id: int,
    request: StrategyUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id
    strategy = (
        db.query(CopyStrategy)
        .filter(CopyStrategy.id == id, CopyStrategy.user_id == user_id)
        .first()
    )
    if not strategy:
        raise NotFoundError("Strategy not found", code="strategy_not_found")

    if request.name is not None:
        strategy.name = request.name
    if request.description is not None:
        strategy.description = request.description
    if request.is_active is not None:
        strategy.is_active = request.is_active

    with rollback_on_error(db):
        db.commit()
        db.refresh(strategy)
    return strategy_to_response(strategy)


@router.delete("/strategies/{id}")
async def delete_strategy(
    id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    user_id = user.id
    strategy = (
        db.query(CopyStrategy)
        .filter(CopyStrategy.id == id, CopyStrategy.user_id == user_id)
        .first()
    )
    if not strategy:
        raise NotFoundError("Strategy not found", code="strategy_not_found")

    with rollback_on_error(db):
        sub_ids = [
            sid
            for (sid,) in db.query(CopySubscriber.id)
            .filter(CopySubscriber.strategy_id == id)
            .all()
        ]
        if sub_ids:
            db.query(CopyPosition).filter(
                CopyPosition.subscriber_id.in_(sub_ids)
            ).delete(synchronize_session=False)
        db.query(CopySubscriber).filter(
            CopySubscriber.strategy_id == id
        ).delete(synchronize_session=False)
        db.query(CopySignal).filter(
            CopySignal.strategy_id == id
        ).delete(synchronize_session=False)
        db.delete(strategy)
        db.commit()
    return {"message": "Strategy deleted"}


@router.post("/subscribers", response_model=SubscriberResponse)
async def create_subscriber(
    request: SubscriberCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    strategy = (
        db.query(CopyStrategy)
        .filter(
            CopyStrategy.id == request.strategy_id,
            CopyStrategy.user_id == user_id,
        )
        .first()
    )
    if not strategy:
        raise NotFoundError("Strategy not found", code="strategy_not_found")

    target_account = (
        db.query(MT5Account)
        .filter(
            MT5Account.id == request.target_account_id,
            MT5Account.user_id == user_id,
        )
        .first()
    )
    if not target_account:
        raise NotFoundError("Target account not found", code="target_account_not_found")

    existing = (
        db.query(CopySubscriber)
        .filter(
            CopySubscriber.user_id == user_id,
            CopySubscriber.strategy_id == request.strategy_id,
            CopySubscriber.target_account_id == request.target_account_id,
        )
        .first()
    )
    if existing:
        raise ConflictError("Subscriber already exists", code="subscriber_exists")

    subscriber = CopySubscriber(
        user_id=user_id,
        strategy_id=request.strategy_id,
        target_account_id=request.target_account_id,
        lot_multiplier=request.lot_multiplier,
        lot_type=request.lot_type,
    )
    with rollback_on_error(db):
        db.add(subscriber)
        db.commit()
        db.refresh(subscriber)
    return subscriber_to_response(subscriber)


@router.get("/subscribers", response_model=List[SubscriberResponse])
async def list_subscribers(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    user_id = user.id
    subscribers = (
        db.query(CopySubscriber).filter(CopySubscriber.user_id == user_id).all()
    )
    return [subscriber_to_response(s) for s in subscribers]


@router.delete("/subscribers/{id}")
async def delete_subscriber(
    id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    user_id = user.id
    subscriber = (
        db.query(CopySubscriber)
        .filter(CopySubscriber.id == id, CopySubscriber.user_id == user_id)
        .first()
    )
    if not subscriber:
        raise NotFoundError("Subscriber not found", code="subscriber_not_found")

    with rollback_on_error(db):
        db.query(CopyPosition).filter(
            CopyPosition.subscriber_id == id
        ).delete(synchronize_session=False)
        db.delete(subscriber)
        db.commit()
    return {"message": "Subscriber deleted"}


@router.post("/dispatch")
async def dispatch_pending_signals(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger execution of pending copy signals for the current user's strategies."""
    results = await asyncio.to_thread(dispatch_signals, db, user_id=user.id)
    return {"dispatched": len(results), "results": results}
