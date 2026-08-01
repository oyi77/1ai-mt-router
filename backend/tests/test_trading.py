"""B6: Trading API tests (account / positions / orders / history / candles / depth)."""
import uuid

import pytest

from app.auth.jwt import create_access_token
from app.models.database import User

_ip = [0]


def _xff():
    _ip[0] += 1
    return f"203.0.113.{_ip[0] % 240 + 1}"


def _headers(**extra):
    h = {"X-Forwarded-For": _xff()}
    h.update(extra)
    return h


@pytest.fixture
def auth(client, db):
    """Real DB user + owned instance; trading endpoints verify ownership via DB."""
    from app.models.database import Instance

    user = User(
        email=f"b6t{uuid.uuid4().hex[:8]}@example.com",
        username=f"b6t{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        Instance(
            id=f"{INSTANCE}-{uuid.uuid4().hex[:8]}",
            name="B6 Trading",
            user_id=user.id,
            docker_container_id=f"{INSTANCE}-{uuid.uuid4().hex[:8]}",
            status="running",
        )
    )
    db.commit()
    token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": "user"}
    )
    return _headers(Authorization=f"Bearer {token}")


class FakeMT5Service:
    """Stands in for app.services.mt5_service.MT5Service.

    Endpoints build `MT5Service(instance_id)` and call its sync methods through
    asyncio.to_thread. Each method name maps to a value in `_responses`
    (None -> falsy result, BaseException -> raise, anything else -> return).
    """

    _responses = {}
    _calls = []

    def __init__(self, instance_id):
        self.instance_id = instance_id

    def __getattr__(self, name):
        def _method(*args, **kwargs):
            FakeMT5Service._calls.append((name, args, kwargs))
            val = FakeMT5Service._responses.get(name)
            if isinstance(val, BaseException):
                raise val
            return val

        return _method


@pytest.fixture(autouse=True)
def _fake_mt5(monkeypatch):
    FakeMT5Service._responses = {}
    FakeMT5Service._calls = []
    monkeypatch.setattr("app.api.trading.MT5Service", FakeMT5Service)


INSTANCE = "inst-b6-001"

ACCOUNT = {
    "login": 12345678,
    "balance": 10000.50,
    "equity": 10050.25,
    "margin": 100.0,
    "free_margin": 9950.25,
    "margin_level": 10050.25,
    "currency": "USD",
    "leverage": 100,
    "server": "MetaQuotes-Demo",
    "name": "B6 Test",
}

POSITION = {
    "ticket": 1001,
    "symbol": "XAUUSD",
    "type": "buy",
    "volume": 0.5,
    "open_price": 2400.00,
    "current_price": 2405.00,
    "sl": 2390.0,
    "tp": 2420.0,
    "profit": 25.0,
    "swap": -0.5,
    "commission": 0.0,
    "comment": "mt5-router",
    "time": "2026-08-01T10:00:00",
}

ORDER = {
    "ticket": 2001,
    "symbol": "EURUSD",
    "type": "buy_limit",
    "volume": 1.0,
    "price": 1.0800,
    "sl": None,
    "tp": 1.0900,
    "magic": 234000,
    "comment": "mt5-router",
    "time_setup": "2026-08-01T10:00:00",
}

PLACED = {
    "ticket": 3001,
    "symbol": "XAUUSD",
    "order_type": "buy",
    "volume": 0.1,
    "price": 2400.0,
    "sl": None,
    "tp": None,
    "status": "filled",
}

DEAL = {
    "ticket": 4001,
    "order": 3001,
    "symbol": "XAUUSD",
    "type": "buy",
    "volume": 0.1,
    "price": 2400.0,
    "profit": 12.5,
    "commission": -1.0,
    "swap": 0.0,
    "time": "2026-08-01T10:00:00",
    "comment": "mt5-router",
}

CANDLE = {
    "time": "2026-08-01T10:00:00",
    "open": 2400.0,
    "high": 2410.0,
    "low": 2398.0,
    "close": 2405.0,
    "tick_volume": 120,
    "spread": 15,
}

BOOK = {
    "symbol": "XAUUSD",
    "timestamp": "2026-08-01T10:00:00",
    "bids": [{"type": "bid", "price": 2399.5, "volume": 1.0, "count": 3}],
    "asks": [{"type": "ask", "price": 2400.5, "volume": 1.0, "count": 2}],
}

SYMBOL = {
    "name": "XAUUSD",
    "point": 0.01,
    "digits": 2,
    "spread": 15,
    "bid": 2399.5,
    "ask": 2400.5,
    "volume_min": 0.01,
    "volume_max": 100.0,
    "volume_step": 0.01,
    "trade_allowed": True,
}

PARTIAL = {
    "ticket": 1001,
    "closed_volume": 0.25,
    "remaining_volume": 0.25,
    "price": 2405.0,
    "status": "partial_closed",
}


def _url(path):
    return f"/api/v1/trading{path}"


# --- account ----------------------------------------------------------------


def test_get_account_info_success(client, auth):
    FakeMT5Service._responses["get_account_info"] = ACCOUNT
    resp = client.get(_url("/account"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 200
    assert resp.json()["login"] == 12345678
    assert resp.json()["name"] == "B6 Test"
    assert FakeMT5Service._calls[0][0] == "get_account_info"


def test_get_account_info_not_connected_503(client, auth):
    FakeMT5Service._responses["get_account_info"] = None
    resp = client.get(_url("/account"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 503


# --- positions --------------------------------------------------------------


def test_get_positions_success(client, auth):
    FakeMT5Service._responses["get_positions"] = [POSITION]
    resp = client.get(_url("/positions"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["ticket"] == 1001
    assert body[0]["symbol"] == "XAUUSD"


def test_get_positions_by_symbol(client, auth):
    FakeMT5Service._responses["get_positions"] = [POSITION]
    resp = client.get(
        _url("/positions"),
        params={"instance_id": INSTANCE, "symbol": "XAUUSD"},
        headers=auth,
    )
    assert resp.status_code == 200
    # symbol forwarded as positional arg to the service
    assert FakeMT5Service._calls[0] == ("get_positions", ("XAUUSD",), {})


def test_get_positions_internal_error_500(client, auth):
    FakeMT5Service._responses["get_positions"] = RuntimeError("mt5 down")
    resp = client.get(_url("/positions"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 500


# --- orders -----------------------------------------------------------------


def test_place_order_success(client, auth):
    FakeMT5Service._responses["place_order"] = PLACED
    resp = client.post(
        _url("/orders"),
        params={"instance_id": INSTANCE},
        json={
            "symbol": "XAUUSD",
            "order_type": "buy",
            "volume": 0.1,
            "price": 2400.0,
        },
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "filled"
    assert body["ticket"] == 3001
    name, args, kwargs = FakeMT5Service._calls[0]
    assert name == "place_order"
    assert kwargs["symbol"] == "XAUUSD"
    assert kwargs["order_type"] == "buy"
    assert kwargs["volume"] == 0.1
    assert kwargs["magic"] == 234000


def test_place_order_missing_symbol_422(client, auth):
    resp = client.post(
        _url("/orders"),
        params={"instance_id": INSTANCE},
        json={"order_type": "buy", "volume": 0.1},
        headers=auth,
    )
    assert resp.status_code == 422


def test_place_order_failure_400(client, auth):
    FakeMT5Service._responses["place_order"] = None
    resp = client.post(
        _url("/orders"),
        params={"instance_id": INSTANCE},
        json={"symbol": "XAUUSD", "order_type": "buy", "volume": 0.1},
        headers=auth,
    )
    assert resp.status_code == 400


def test_get_pending_orders_success(client, auth):
    FakeMT5Service._responses["get_pending_orders"] = [ORDER]
    resp = client.get(_url("/orders"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["ticket"] == 2001
    assert body[0]["type"] == "buy_limit"


def test_cancel_order_success(client, auth):
    FakeMT5Service._responses["cancel_pending_order"] = True
    resp = client.delete(
        _url("/orders/2001"), params={"instance_id": INSTANCE}, headers=auth
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelled", "ticket": 2001}
    assert FakeMT5Service._calls[0] == ("cancel_pending_order", (2001,), {})


def test_cancel_order_failure_400(client, auth):
    FakeMT5Service._responses["cancel_pending_order"] = False
    resp = client.delete(
        _url("/orders/2001"), params={"instance_id": INSTANCE}, headers=auth
    )
    assert resp.status_code == 400


def test_modify_order_success(client, auth):
    FakeMT5Service._responses["modify_pending_order"] = True
    resp = client.put(
        _url("/orders/2001/modify"),
        params={"instance_id": INSTANCE},
        json={"price": 1.0750, "sl": 1.0700, "tp": 1.0900},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "modified", "ticket": 2001}
    name, args, kwargs = FakeMT5Service._calls[0]
    assert name == "modify_pending_order"
    assert args == (2001,)
    assert kwargs == {
        "price": 1.0750,
        "sl": 1.0700,
        "tp": 1.0900,
        "sl_clear": False,
        "tp_clear": False,
    }


def test_modify_order_failure_400(client, auth):
    FakeMT5Service._responses["modify_pending_order"] = False
    resp = client.put(
        _url("/orders/2001/modify"),
        params={"instance_id": INSTANCE},
        json={"price": 1.0750},
        headers=auth,
    )
    assert resp.status_code == 400


# --- position actions -------------------------------------------------------


def test_close_position_success(client, auth):
    FakeMT5Service._responses["close_position"] = True
    resp = client.post(
        _url("/positions/1001/close"),
        params={"instance_id": INSTANCE},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "closed", "ticket": 1001}


def test_close_position_failure_400(client, auth):
    FakeMT5Service._responses["close_position"] = False
    resp = client.post(
        _url("/positions/1001/close"),
        params={"instance_id": INSTANCE},
        headers=auth,
    )
    assert resp.status_code == 400


def test_modify_position_success(client, auth):
    FakeMT5Service._responses["modify_position"] = True
    resp = client.put(
        _url("/positions/1001/modify"),
        params={"instance_id": INSTANCE},
        json={"sl": 2390.0, "tp": 2420.0},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "modified", "ticket": 1001}
    name, args, kwargs = FakeMT5Service._calls[0]
    assert name == "modify_position"
    assert args == (1001,)
    assert kwargs == {
        "sl": 2390.0,
        "tp": 2420.0,
        "sl_clear": False,
        "tp_clear": False,
    }


def test_modify_position_failure_400(client, auth):
    FakeMT5Service._responses["modify_position"] = False
    resp = client.put(
        _url("/positions/1001/modify"),
        params={"instance_id": INSTANCE},
        json={"sl": 2390.0},
        headers=auth,
    )
    assert resp.status_code == 400


def test_partial_close_success(client, auth):
    FakeMT5Service._responses["partial_close_position"] = PARTIAL
    resp = client.post(
        _url("/positions/1001/partial-close"),
        params={"instance_id": INSTANCE},
        json={"volume": 0.25},
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["closed_volume"] == 0.25
    assert body["remaining_volume"] == 0.25
    name, args, kwargs = FakeMT5Service._calls[0]
    assert name == "partial_close_position"
    assert args == (1001,)
    assert kwargs == {"volume": 0.25}


def test_partial_close_failure_400(client, auth):
    FakeMT5Service._responses["partial_close_position"] = None
    resp = client.post(
        _url("/positions/1001/partial-close"),
        params={"instance_id": INSTANCE},
        json={"volume": 0.25},
        headers=auth,
    )
    assert resp.status_code == 400


def test_partial_close_zero_volume_422(client, auth):
    resp = client.post(
        _url("/positions/1001/partial-close"),
        params={"instance_id": INSTANCE},
        json={"volume": 0},
        headers=auth,
    )
    assert resp.status_code == 422


# --- symbols ----------------------------------------------------------------


def test_get_symbol_info_success(client, auth):
    FakeMT5Service._responses["get_symbol_info"] = SYMBOL
    resp = client.get(_url("/symbols/XAUUSD"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "XAUUSD"
    assert body["trade_allowed"] is True
    assert FakeMT5Service._calls[0] == ("get_symbol_info", ("XAUUSD",), {})


def test_get_symbol_info_404(client, auth):
    FakeMT5Service._responses["get_symbol_info"] = None
    resp = client.get(_url("/symbols/XAUUSD"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 404


# --- history ----------------------------------------------------------------


def test_get_history_success(client, auth):
    FakeMT5Service._responses["get_history_deals"] = [DEAL]
    resp = client.get(
        _url("/history"),
        params={"instance_id": INSTANCE, "symbol": "XAUUSD", "days": 7},
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["ticket"] == 4001
    assert body[0]["profit"] == 12.5
    # (symbol, days) passed as positional args
    assert FakeMT5Service._calls[0] == ("get_history_deals", ("XAUUSD", 7), {})


def test_get_history_invalid_days_422(client, auth):
    resp = client.get(
        _url("/history"),
        params={"instance_id": INSTANCE, "days": 0},
        headers=auth,
    )
    assert resp.status_code == 422


def test_get_history_too_many_days_422(client, auth):
    resp = client.get(
        _url("/history"),
        params={"instance_id": INSTANCE, "days": 366},
        headers=auth,
    )
    assert resp.status_code == 422


# --- candles & depth --------------------------------------------------------


def test_get_candles_success(client, auth):
    FakeMT5Service._responses["get_candle_data"] = [CANDLE]
    resp = client.get(
        _url("/symbols/XAUUSD/candles"),
        params={"instance_id": INSTANCE, "timeframe": "M5", "count": 10},
        headers=auth,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["close"] == 2405.0
    assert body[0]["tick_volume"] == 120
    assert FakeMT5Service._calls[0] == ("get_candle_data", ("XAUUSD", "M5", 10), {})


def test_get_candles_too_many_422(client, auth):
    resp = client.get(
        _url("/symbols/XAUUSD/candles"),
        params={"instance_id": INSTANCE, "count": 1001},
        headers=auth,
    )
    assert resp.status_code == 422


def test_get_order_book_success(client, auth):
    FakeMT5Service._responses["get_order_book"] = BOOK
    resp = client.get(_url("/symbols/XAUUSD/depth"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["bids"][0]["price"] == 2399.5
    assert body["asks"][0]["count"] == 2


def test_get_order_book_404(client, auth):
    FakeMT5Service._responses["get_order_book"] = None
    resp = client.get(_url("/symbols/XAUUSD/depth"), params={"instance_id": INSTANCE}, headers=auth)
    assert resp.status_code == 404
