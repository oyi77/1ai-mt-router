import socket
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone

from app.core.docker_client import get_docker_client

logger = logging.getLogger(__name__)

# Timeframe mapping for candle data
TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M2": "TIMEFRAME_M2",
    "M3": "TIMEFRAME_M3",
    "M4": "TIMEFRAME_M4",
    "M5": "TIMEFRAME_M5",
    "M6": "TIMEFRAME_M6",
    "M10": "TIMEFRAME_M10",
    "M12": "TIMEFRAME_M12",
    "M15": "TIMEFRAME_M15",
    "M20": "TIMEFRAME_M20",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H2": "TIMEFRAME_H2",
    "H3": "TIMEFRAME_H3",
    "H4": "TIMEFRAME_H4",
    "H6": "TIMEFRAME_H6",
    "H8": "TIMEFRAME_H8",
    "H12": "TIMEFRAME_H12",
    "D1": "TIMEFRAME_D1",
    "W1": "TIMEFRAME_W1",
    "MN1": "TIMEFRAME_MN1",
}


class MT5Service:
    def __init__(self, instance_id: str, host: str = "localhost"):
        self.instance_id = instance_id
        self.host = host
        self._port = 18812
        self._mt5 = None
        self._container_port = None

    def _get_container_port(self):
        if self._container_port:
            return self._container_port

        try:
            client = get_docker_client()
            container = client.containers.get(self.instance_id)
            ports = container.ports.get("18812/tcp")
            if ports:
                self._container_port = int(ports[0]["HostPort"])
                return self._container_port
        except Exception as e:
            logger.error(f"Error getting container port: {e}")

        return self._port

    def _check_server(self, timeout: int = 5) -> bool:
        port = self._get_container_port()
        try:
            sock = socket.create_connection((self.host, port), timeout=timeout)
            sock.close()
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def check_server(self, timeout: int = 5) -> bool:
        """Public reachability probe for this instance's MT5 gateway.

        Bundle B12 (C18): callers such as account status checks probe the
        server before connecting; keep the socket check behind a public API
        instead of reaching into the private ``_check_server``.
        """
        return self._check_server(timeout=timeout)

    def _connect(self):
        if self._mt5 is None:
            if not self._check_server():
                raise ConnectionError(
                    f"MT5 server unreachable at {self.host}:{self._get_container_port()}"
                )

            try:
                from mt5linux import MetaTrader5

                self._mt5 = MetaTrader5(host=self.host, port=self._get_container_port())
                if not self._mt5.initialize():
                    raise ConnectionError(
                        f"MT5 initialize failed: {self._mt5.last_error()}"
                    )
                logger.info(
                    f"Connected to MT5 at {self.host}:{self._get_container_port()}"
                )
            except ImportError:
                raise ImportError("mt5linux not installed")
            except Exception as e:
                raise ConnectionError(f"MT5 connection error: {e}")

        return self._mt5

    def connect(self, password: str, server: str) -> bool:
        if not self._check_server():
            raise ConnectionError(
                f"MT5 server unreachable at {self.host}:{self._get_container_port()}"
            )

        try:
            from mt5linux import MetaTrader5

            self._mt5 = MetaTrader5(host=self.host, port=self._get_container_port())

            initialized = self._mt5.initialize(
                login=0, password=password, server=server, timeout=60000
            )

            if not initialized:
                error = self._mt5.last_error()
                logger.error(f"MT5 login failed: {error}")
                self._mt5 = None
                return False

            logger.info(f"Successfully connected to MT5 server: {server}")
            return True

        except ImportError:
            raise ImportError("mt5linux not installed")
        except Exception as e:
            logger.error(f"MT5 connection error: {e}")
            self._mt5 = None
            return False

    def disconnect(self) -> bool:
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
                logger.info("MT5 disconnected")
            except Exception as e:
                logger.warning(f"MT5 shutdown warning: {e}")
            finally:
                self._mt5 = None
        return True

    def is_connected(self) -> bool:
        if self._mt5 is None:
            return False
        try:
            account = self._mt5.account_info()
            return account is not None
        except Exception:
            return False

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            info = mt5.account_info()
            if info:
                return {
                    "login": info.login,
                    "balance": float(info.balance),
                    "equity": float(info.equity),
                    "margin": float(info.margin),
                    "free_margin": float(info.margin_free),
                    "margin_level": float(info.margin_level)
                    if info.margin_level
                    else 0,
                    "currency": info.currency,
                    "leverage": info.leverage,
                    "server": info.server,
                    "name": info.name,
                }
            return None
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return None

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            positions = (
                mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
            )
            if not positions:
                return []

            return [
                {
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "type": "BUY" if pos.type == 0 else "SELL",
                    "volume": float(pos.volume),
                    "open_price": float(pos.price_open),
                    "current_price": float(pos.price_current),
                    "sl": float(pos.sl) if pos.sl else None,
                    "tp": float(pos.tp) if pos.tp else None,
                    "profit": float(pos.profit),
                    "swap": float(pos.swap),
                    "commission": float(pos.commission),
                    "comment": pos.comment,
                    "time": datetime.fromtimestamp(pos.time, tz=timezone.utc).isoformat(),
                }
                for pos in positions
            ]
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    def place_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        magic: int = 234000,
        comment: str = "mt5-router",
    ) -> Optional[Dict[str, Any]]:
        try:
            mt5 = self._connect()

            if price is None:
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    return None
                price = tick.ask if order_type.upper() == "BUY" else tick.bid

            type_map = {
                "BUY": mt5.ORDER_TYPE_BUY,
                "SELL": mt5.ORDER_TYPE_SELL,
                "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
                "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
                "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
                "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
                "BUY_STOP_LIMIT": mt5.ORDER_TYPE_BUY_STOP_LIMIT,
                "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
            }

            if order_type.upper() not in type_map:
                raise ValueError(f"Invalid order type: {order_type}")

            is_pending = order_type.upper() in [
                "BUY_LIMIT",
                "SELL_LIMIT",
                "BUY_STOP",
                "SELL_STOP",
                "BUY_STOP_LIMIT",
                "SELL_STOP_LIMIT",
            ]
            is_stop_limit = order_type.upper() in ["BUY_STOP_LIMIT", "SELL_STOP_LIMIT"]
            action = mt5.TRADE_ACTION_PENDING if is_pending else mt5.TRADE_ACTION_DEAL

            request = {
                "action": action,
                "symbol": symbol,
                "volume": float(volume),
                "type": type_map[order_type.upper()],
                "price": float(price),
                "deviation": 20,
                "magic": magic,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }

            if is_stop_limit and stop_price is not None:
                request["price_stoplimit"] = float(stop_price)

            if sl is not None:
                request["sl"] = float(sl)
            if tp is not None:
                request["tp"] = float(tp)

            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return {
                    "ticket": result.order,
                    "symbol": symbol,
                    "order_type": order_type,
                    "volume": volume,
                    "price": float(price),
                    "sl": sl,
                    "tp": tp,
                    "status": "filled",
                }

            logger.error(f"Order failed: {result.comment if result else 'No result'}")
            return None
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def close_position(self, ticket: int) -> bool:
        try:
            mt5 = self._connect()
            positions = mt5.positions_get()
            if not positions:
                return False

            pos = next((p for p in positions if p.ticket == ticket), None)
            if not pos:
                return False

            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return False

            close_type = (
                mt5.ORDER_TYPE_SELL
                if pos.type == mt5.ORDER_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )
            price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": float(pos.volume),
                "type": close_type,
                "position": ticket,
                "price": float(price),
                "deviation": 20,
                "magic": 234000,
                "comment": "mt5-router-close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }

            result = mt5.order_send(request)
            return result and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logger.error(f"Error closing position: {e}")
            return False

    def cancel_pending_order(self, ticket: int) -> bool:
        try:
            mt5 = self._connect()
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket,
                "comment": "mt5-router-cancel",
            }
            result = mt5.order_send(request)
            return result and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            orders = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
            if not orders:
                return []

            type_map = {
                2: "BUY_LIMIT",
                3: "SELL_LIMIT",
                4: "BUY_STOP",
                5: "SELL_STOP",
                6: "BUY_STOP_LIMIT",
                7: "SELL_STOP_LIMIT",
            }

            return [
                {
                    "ticket": order.ticket,
                    "symbol": order.symbol,
                    "type": type_map.get(order.type, "UNKNOWN"),
                    "volume": float(order.volume_initial),
                    "price": float(order.price_open),
                    "sl": float(order.sl) if order.sl else None,
                    "tp": float(order.tp) if order.tp else None,
                    "magic": order.magic,
                    "comment": order.comment,
                    "time_setup": datetime.fromtimestamp(order.time_setup, tz=timezone.utc).isoformat(),
                }
                for order in orders
            ]
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            info = mt5.symbol_info(symbol)
            if info:
                return {
                    "name": info.name,
                    "point": info.point,
                    "digits": info.digits,
                    "spread": info.spread,
                    "bid": float(info.bid) if info.bid else None,
                    "ask": float(info.ask) if info.ask else None,
                    "volume_min": float(info.volume_min),
                    "volume_max": float(info.volume_max),
                    "volume_step": float(info.volume_step),
                    "trade_allowed": info.trade_allowed,
                }
            return None
        except Exception as e:
            logger.error(f"Error getting symbol info: {e}")
            return None

    def get_history_deals(
        self, symbol: Optional[str] = None, days: int = 30
    ) -> List[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            end = datetime.now()
            start = end - timedelta(days=days)

            if symbol:
                deals = mt5.history_deals_get(symbol, start, end)
            else:
                deals = mt5.history_deals_get(start, end)

            if not deals:
                return []

            return [
                {
                    "ticket": deal.ticket,
                    "order": deal.order,
                    "symbol": deal.symbol,
                    "type": "BUY" if deal.type == 0 else "SELL",
                    "volume": float(deal.volume),
                    "price": float(deal.price),
                    "profit": float(deal.profit),
                    "commission": float(deal.commission),
                    "swap": float(deal.swap),
                    "time": datetime.fromtimestamp(deal.time, tz=timezone.utc).isoformat(),
                    "comment": deal.comment,
                }
                for deal in deals
            ]
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []

    def modify_position(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        sl_clear: bool = False,
        tp_clear: bool = False,
    ) -> bool:
        try:
            mt5 = self._connect()
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "comment": "mt5-router-modify",
            }
            if sl_clear:
                request["sl"] = 0.0
            elif sl is not None:
                request["sl"] = float(sl)
            if tp_clear:
                request["tp"] = 0.0
            elif tp is not None:
                request["tp"] = float(tp)
            result = mt5.order_send(request)
            return result and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logger.error(f"Error modifying position {ticket}: {e}")
            return False

    def partial_close_position(
        self, ticket: int, volume: float
    ) -> Optional[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            positions = mt5.positions_get()
            if not positions:
                return None

            pos = next((p for p in positions if p.ticket == ticket), None)
            if not pos:
                return None

            if volume >= float(pos.volume):
                logger.error(
                    f"Partial close volume {volume} >= position volume {pos.volume}"
                )
                return None

            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return None

            close_type = (
                mt5.ORDER_TYPE_SELL
                if pos.type == mt5.ORDER_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )
            price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": float(volume),
                "type": close_type,
                "position": ticket,
                "price": float(price),
                "deviation": 20,
                "magic": 234000,
                "comment": "mt5-router-partial-close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                return {
                    "ticket": ticket,
                    "closed_volume": volume,
                    "remaining_volume": float(pos.volume) - volume,
                    "price": float(price),
                    "status": "partial_closed",
                }
            logger.error(
                f"Partial close failed: {result.comment if result else 'No result'}"
            )
            return None
        except Exception as e:
            logger.error(f"Error partial closing position {ticket}: {e}")
            return None

    def modify_pending_order(
        self,
        ticket: int,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        sl_clear: bool = False,
        tp_clear: bool = False,
    ) -> bool:
        try:
            mt5 = self._connect()
            orders = mt5.orders_get()
            if not orders:
                return False

            order = next((o for o in orders if o.ticket == ticket), None)
            if not order:
                return False

            request = {
                "action": mt5.TRADE_ACTION_MODIFY,
                "order": ticket,
                "price": float(price) if price is not None else float(order.price_open),
                "comment": "mt5-router-modify-order",
            }
            if sl_clear:
                request["sl"] = 0.0
            elif sl is not None:
                request["sl"] = float(sl)
            if tp_clear:
                request["tp"] = 0.0
            elif tp is not None:
                request["tp"] = float(tp)

            result = mt5.order_send(request)
            return result and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logger.error(f"Error modifying pending order {ticket}: {e}")
            return False

    def get_current_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                return {
                    "symbol": symbol,
                    "bid": float(tick.bid),
                    "ask": float(tick.ask),
                    "last": float(tick.last),
                    "volume": int(tick.volume),
                    "time": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
                    "flags": tick.flags,
                }
            return None
        except Exception as e:
            logger.error(f"Error getting tick for {symbol}: {e}")
            return None

    def get_candle_data(
        self, symbol: str, timeframe: str = "M1", count: int = 100
    ) -> List[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            tf_attr = TIMEFRAME_MAP.get(timeframe.upper())
            if not tf_attr:
                logger.error(f"Invalid timeframe: {timeframe}")
                return []

            tf = getattr(mt5, tf_attr, None)
            if tf is None:
                logger.error(f"Timeframe not available: {timeframe}")
                return []

            rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
            if rates is None or len(rates) == 0:
                return []

            return [
                {
                    "time": datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc).isoformat(),
                    "open": float(rate["open"]),
                    "high": float(rate["high"]),
                    "low": float(rate["low"]),
                    "close": float(rate["close"]),
                    "tick_volume": int(rate["tick_volume"]),
                    "spread": int(rate["spread"]),
                }
                for rate in rates
            ]
        except Exception as e:
            logger.error(f"Error getting candle data for {symbol}: {e}")
            return []

    def get_order_book(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            mt5 = self._connect()
            book = mt5.market_book_get(symbol)
            if book is None:
                return None

            bids = []
            asks = []
            for item in book:
                level = {
                    "type": "buy" if item.type == mt5.BOOK_TYPE_BUY else "sell",
                    "price": float(item.price),
                    "volume": float(item.volume),
                    "count": int(item.count),
                }
                if item.type == mt5.BOOK_TYPE_BUY:
                    bids.append(level)
                else:
                    asks.append(level)

            return {
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "bids": bids,
                "asks": asks,
            }
        except Exception as e:
            logger.error(f"Error getting order book for {symbol}: {e}")
            return None

    def subscribe_to_ticks(self, symbols: List[str]) -> bool:
        try:
            mt5 = self._connect()
            for symbol in symbols:
                if not mt5.symbol_select(symbol, True):
                    logger.warning(f"Failed to select symbol: {symbol}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to ticks: {e}")
            return False

    def unsubscribe_from_ticks(self, symbols: List[str]) -> bool:
        try:
            mt5 = self._connect()
            for symbol in symbols:
                mt5.symbol_select(symbol, False)
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from ticks: {e}")
            return False
