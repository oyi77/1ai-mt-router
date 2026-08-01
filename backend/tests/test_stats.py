"""B6 tests for the trading statistics API (app.api.statistics).

Statistics endpoints require a real owned ``Instance`` row (ownership is
checked against the DB), so every test seeds a unique user + instance. The
MT5 bridge is faked at the module level.
"""
import uuid

import pytest

from app.auth.jwt import create_access_token
from app.models.database import Instance, User

from app.api import statistics as stats_module


# --- per-request fake client IP, so the shared rate-limit bucket never trips ---
_ip_counter = [0]


def _xff():
    _ip_counter[0] += 1
    return f"203.0.113.{_ip_counter[0] % 240 + 1}"


def _headers(user_id):
    token = create_access_token(
        {"sub": str(user_id), "username": "tester", "role": "user"}
    )
    return {"Authorization": f"Bearer {token}", "X-Forwarded-For": _xff()}


def _make_user(db):
    username = f"u{uuid.uuid4().hex[:8]}"
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_instance(db, user):
    row = Instance(
        id=f"inst-{uuid.uuid4().hex[:8]}",
        name="mt5-stats",
        user_id=user.id,
        status="running",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class FakeMT5Service:
    """Stands in for app.services.mt5_service.MT5Service.

    Endpoints call `get_history_deals(days=...)` (keyword) and
    `get_account_info()` through asyncio.to_thread. None -> falsy, BaseException
    -> raise, anything else -> return.
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
    monkeypatch.setattr("app.api.statistics.MT5Service", FakeMT5Service)


def _url(path):
    return f"/api/v1/stats{path}"


# 3 deals: two winners (+100, +50), one loser (-30).
DEALS = [
    {"time": "2026-07-01T10:00:00", "profit": 100.0, "symbol": "XAUUSD", "volume": 0.5},
    {"time": "2026-07-02T10:00:00", "profit": -30.0, "symbol": "EURUSD", "volume": 1.0},
    {"time": "2026-07-03T10:00:00", "profit": 50.0, "symbol": "XAUUSD", "volume": 0.5},
]


# --- /summary ---------------------------------------------------------------


def test_summary_success(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_history_deals"] = DEALS

    resp = client.get(
        _url("/summary"), params={"instance_id": inst.id, "days": 7}, headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_trades"] == 3
    assert body["winning_trades"] == 2
    assert body["losing_trades"] == 1
    assert body["win_rate"] == pytest.approx(2 / 3 * 100)
    assert body["total_profit"] == 150.0
    assert body["total_loss"] == 30.0
    assert body["net_profit"] == 120.0
    assert body["profit_factor"] == 5.0
    assert body["average_win"] == 75.0
    assert body["average_loss"] == 30.0
    assert body["largest_win"] == 100.0
    assert body["largest_loss"] == -30.0
    assert body["average_trade_duration"] == 0
    assert body["max_drawdown"] == 30.0
    assert body["sharpe_ratio"] is None
    # days forwarded as a keyword argument
    assert FakeMT5Service._calls[0] == ("get_history_deals", (), {"days": 7})


def test_summary_empty_deals_zeroes(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_history_deals"] = []

    resp = client.get(
        _url("/summary"), params={"instance_id": inst.id}, headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_trades"] == 0
    assert body["win_rate"] == 0
    assert body["net_profit"] == 0
    assert body["profit_factor"] == 0
    assert body["max_drawdown"] == 0


@pytest.mark.parametrize("days", [0, 366])
def test_summary_invalid_days_422(client, db, days):
    user = _make_user(db)
    inst = _make_instance(db, user)
    resp = client.get(
        _url("/summary"), params={"instance_id": inst.id, "days": days}, headers=_headers(user.id)
    )
    assert resp.status_code == 422


def test_summary_instance_not_found_404(client, db):
    user = _make_user(db)
    resp = client.get(
        _url("/summary"), params={"instance_id": "inst-nope"}, headers=_headers(user.id)
    )
    assert resp.status_code == 404


def test_summary_mt5_error_503(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_history_deals"] = RuntimeError("mt5 down")

    resp = client.get(
        _url("/summary"), params={"instance_id": inst.id}, headers=_headers(user.id)
    )
    assert resp.status_code == 503


# --- /daily ---------------------------------------------------------------


def test_daily_summary_success(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_history_deals"] = DEALS

    resp = client.get(
        _url("/daily"), params={"instance_id": inst.id, "days": 7}, headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [row["date"] for row in body] == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
    ]
    assert body[0]["trades"] == 1
    assert body[0]["profit"] == 100.0
    assert body[0]["wins"] == 1
    assert body[0]["losses"] == 0
    assert body[1]["profit"] == -30.0
    assert body[1]["wins"] == 0
    assert body[1]["losses"] == 1


def test_daily_summary_mt5_error_503(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_history_deals"] = RuntimeError("mt5 down")

    resp = client.get(
        _url("/daily"), params={"instance_id": inst.id}, headers=_headers(user.id)
    )
    assert resp.status_code == 503


# --- /symbols -------------------------------------------------------------


def test_symbol_stats_success(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_history_deals"] = DEALS

    resp = client.get(
        _url("/symbols"), params={"instance_id": inst.id, "days": 7}, headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    # sorted by abs(net_profit) desc -> XAUUSD (150) before EURUSD (-30)
    assert [row["symbol"] for row in body] == ["XAUUSD", "EURUSD"]
    assert body[0]["trades"] == 2
    assert body[0]["win_rate"] == 100.0
    assert body[0]["net_profit"] == 150.0
    assert body[0]["total_volume"] == 1.0
    assert body[1]["win_rate"] == 0.0
    assert body[1]["net_profit"] == -30.0


# --- /equity-curve --------------------------------------------------------


def test_equity_curve_success(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_account_info"] = {"equity": 1000.0}
    FakeMT5Service._responses["get_history_deals"] = DEALS

    resp = client.get(
        _url("/equity-curve"), params={"instance_id": inst.id, "days": 7}, headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    # reversed walk: C(950,1000) -> B(980,950) -> A(880,980), then final point,
    # re-sorted by timestamp.
    assert len(body) == 4
    assert body[0]["equity"] == 880.0
    assert body[0]["balance"] == 980.0
    assert body[1]["equity"] == 980.0
    assert body[1]["balance"] == 950.0
    assert body[2]["equity"] == 950.0
    assert body[2]["balance"] == 1000.0
    # final point = current equity/balance
    assert body[3]["equity"] == 1000.0
    assert body[3]["balance"] == 1000.0
    # deals fetched as a positional call, account info with no args
    assert FakeMT5Service._calls[0] == ("get_account_info", (), {})
    assert FakeMT5Service._calls[1] == ("get_history_deals", (), {"days": 7})


def test_equity_curve_no_deals(client, db):
    user = _make_user(db)
    inst = _make_instance(db, user)
    FakeMT5Service._responses["get_account_info"] = {"equity": 500.0}
    FakeMT5Service._responses["get_history_deals"] = []

    resp = client.get(
        _url("/equity-curve"), params={"instance_id": inst.id}, headers=_headers(user.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    # No deals -> no historical points; the "final" point is only appended when
    # there is at least one equity point (see statistics.py get_equity_curve).
    assert body == []
