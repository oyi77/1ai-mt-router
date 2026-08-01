from fastapi import APIRouter, HTTPException, WebSocket, Depends, Query
from typing import List, Optional
from pydantic import BaseModel, Field
import asyncio
import logging

from jose import JWTError, jwt

from app.config import settings
from app.auth.jwt import get_current_user
from app.core.exceptions import (
    AppError,
    BadRequestError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.services.mt5_service import MT5Service

router = APIRouter()
logger = logging.getLogger(__name__)

# Max number of symbols a single WebSocket tick stream may subscribe to (B12/C4).
MAX_WS_SYMBOLS = 10

VALID_ORDER_TYPES = {
    "BUY",
    "SELL",
    "BUY_LIMIT",
    "SELL_LIMIT",
    "BUY_STOP",
    "SELL_STOP",
    "BUY_STOP_LIMIT",
    "SELL_STOP_LIMIT",
}


class OrderRequest(BaseModel):
    symbol: str
    order_type: str
    volume: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    magic: int = 234000
    comment: str = "mt5-router"


class OrderResponse(BaseModel):
    ticket: int
    symbol: str
    order_type: str
    volume: float
    price: float
    sl: Optional[float]
    tp: Optional[float]
    status: str


class ModifyPositionRequest(BaseModel):
    sl: Optional[float] = None
    tp: Optional[float] = None
    sl_clear: bool = False
    tp_clear: bool = False


class PartialCloseRequest(BaseModel):
    volume: float = Field(gt=0)


class ModifyOrderRequest(BaseModel):
    price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    sl_clear: bool = False
    tp_clear: bool = False


class CandleData(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int


class OrderBookLevel(BaseModel):
    type: str
    price: float
    volume: float
    count: int


class OrderBookData(BaseModel):
    symbol: str
    timestamp: str
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]


class AccountInfo(BaseModel):
    login: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str
    leverage: int
    server: str
    name: str


class PositionData(BaseModel):
    ticket: int
    symbol: str
    type: str
    volume: float
    open_price: float
    current_price: float
    sl: Optional[float]
    tp: Optional[float]
    profit: float
    swap: float
    commission: float
    comment: Optional[str]
    time: str


class OrderData(BaseModel):
    ticket: int
    symbol: str
    type: str
    volume: float
    price: float
    sl: Optional[float]
    tp: Optional[float]
    magic: int
    comment: Optional[str]
    time_setup: str


class DealData(BaseModel):
    ticket: int
    order: int
    symbol: str
    type: str
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    time: str
    comment: Optional[str]


class SymbolInfo(BaseModel):
    name: str
    point: float
    digits: int
    spread: int
    bid: Optional[float]
    ask: Optional[float]
    volume_min: float
    volume_max: float
    volume_step: float
    trade_allowed: bool


class TradeActionResult(BaseModel):
    status: str
    ticket: int


class PartialCloseResult(BaseModel):
    ticket: int
    closed_volume: float
    remaining_volume: float
    price: float
    status: str


@router.get("/account", response_model=AccountInfo)
async def get_account_info(
    instance_id: str = Query(...), user: dict = Depends(get_current_user)
):
    try:
        mt5 = MT5Service(instance_id)
        account = await asyncio.to_thread(mt5.get_account_info)
        if not account:
            raise ServiceUnavailableError(
                "MT5 not connected", code="mt5_not_connected"
            )
        return account
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting account info: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.get("/positions", response_model=List[PositionData])
async def get_positions(
    instance_id: str = Query(...),
    symbol: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        return await asyncio.to_thread(mt5.get_positions, symbol)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.post("/orders", response_model=OrderResponse)
async def place_order(
    order: OrderRequest,
    instance_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        if order.order_type.upper() not in VALID_ORDER_TYPES:
            raise BadRequestError("Invalid order type", code="invalid_order_type")
        mt5 = MT5Service(instance_id)
        result = await asyncio.to_thread(
            mt5.place_order,
            symbol=order.symbol,
            order_type=order.order_type,
            volume=order.volume,
            price=order.price,
            stop_price=order.stop_price,
            sl=order.sl,
            tp=order.tp,
            magic=order.magic,
            comment=order.comment,
        )
        if not result:
            raise BadRequestError("Order failed", code="order_failed")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.get("/orders", response_model=List[OrderData])
async def get_orders(
    instance_id: str = Query(...),
    symbol: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        return await asyncio.to_thread(mt5.get_pending_orders, symbol)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting orders: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.delete("/orders/{ticket}", response_model=TradeActionResult)
async def cancel_order(
    ticket: int, instance_id: str = Query(...), user: dict = Depends(get_current_user)
):
    try:
        mt5 = MT5Service(instance_id)
        success = await asyncio.to_thread(mt5.cancel_pending_order, ticket)
        if not success:
            raise BadRequestError(
                "Failed to cancel order", code="cancel_order_failed"
            )
        return {"status": "cancelled", "ticket": ticket}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.post("/positions/{ticket}/close", response_model=TradeActionResult)
async def close_position(
    ticket: int, instance_id: str = Query(...), user: dict = Depends(get_current_user)
):
    try:
        mt5 = MT5Service(instance_id)
        success = await asyncio.to_thread(mt5.close_position, ticket)
        if not success:
            raise BadRequestError(
                "Failed to close position", code="close_position_failed"
            )
        return {"status": "closed", "ticket": ticket}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing position: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.get("/symbols/{symbol}", response_model=SymbolInfo)
async def get_symbol_info(
    symbol: str, instance_id: str = Query(...), user: dict = Depends(get_current_user)
):
    try:
        mt5 = MT5Service(instance_id)
        info = await asyncio.to_thread(mt5.get_symbol_info, symbol)
        if not info:
            raise NotFoundError("Symbol not found", code="symbol_not_found")
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting symbol info: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.get("/history", response_model=List[DealData])
async def get_history(
    instance_id: str = Query(...),
    symbol: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        return await asyncio.to_thread(mt5.get_history_deals, symbol, days)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.put("/positions/{ticket}/modify", response_model=TradeActionResult)
async def modify_position(
    ticket: int,
    body: ModifyPositionRequest,
    instance_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        success = await asyncio.to_thread(
            mt5.modify_position,
            ticket,
            sl=body.sl,
            tp=body.tp,
            sl_clear=body.sl_clear,
            tp_clear=body.tp_clear,
        )
        if not success:
            raise BadRequestError(
                "Failed to modify position", code="modify_position_failed"
            )
        return {"status": "modified", "ticket": ticket}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error modifying position: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.post("/positions/{ticket}/partial-close", response_model=PartialCloseResult)
async def partial_close_position(
    ticket: int,
    body: PartialCloseRequest,
    instance_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        result = await asyncio.to_thread(
            mt5.partial_close_position, ticket, volume=body.volume
        )
        if not result:
            raise BadRequestError(
                "Failed to partially close position",
                code="partial_close_failed",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error partial closing position: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.put("/orders/{ticket}/modify", response_model=TradeActionResult)
async def modify_order(
    ticket: int,
    body: ModifyOrderRequest,
    instance_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        success = await asyncio.to_thread(
            mt5.modify_pending_order,
            ticket,
            price=body.price,
            sl=body.sl,
            tp=body.tp,
            sl_clear=body.sl_clear,
            tp_clear=body.tp_clear,
        )
        if not success:
            raise BadRequestError(
                "Failed to modify order", code="modify_order_failed"
            )
        return {"status": "modified", "ticket": ticket}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error modifying order: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.get("/symbols/{symbol}/candles", response_model=List[CandleData])
async def get_candles(
    symbol: str,
    timeframe: str = Query("M1"),
    count: int = Query(100, le=1000),
    instance_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        return await asyncio.to_thread(mt5.get_candle_data, symbol, timeframe, count)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting candles: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.get("/symbols/{symbol}/depth", response_model=OrderBookData)
async def get_order_book(
    symbol: str,
    instance_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        mt5 = MT5Service(instance_id)
        book = await asyncio.to_thread(mt5.get_order_book, symbol)
        if not book:
            raise NotFoundError(
                "Order book not available", code="order_book_unavailable"
            )
        return book
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order book: {e}")
        raise AppError(
            status_code=500, code="internal_error", message="Internal server error"
        )


@router.websocket("/ticks")
async def ticks_websocket(
    websocket: WebSocket,
    instance_id: str = Query(...),
    symbols: str = Query("XAUUSD"),
    token: str = Query(...),
):
    # B12 (C4): require a valid auth token and cap the symbol list.
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        if not payload.get("sub"):
            await websocket.close(code=4401)
            return
    except JWTError:
        await websocket.close(code=4401)
        return

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] or ["XAUUSD"]
    if len(symbol_list) > MAX_WS_SYMBOLS:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    mt5 = MT5Service(instance_id)
    try:
        await asyncio.to_thread(mt5.subscribe_to_ticks, symbol_list)
        while True:
            for symbol in symbol_list:
                tick = await asyncio.to_thread(mt5.get_current_tick, symbol)
                if tick:
                    await websocket.send_json(tick)
            await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        try:
            await asyncio.to_thread(mt5.unsubscribe_from_ticks, symbol_list)
        except Exception:
            pass
        await websocket.close()
