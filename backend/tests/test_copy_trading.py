"""F4: Copy-trading execution tests (lot sizing / dispatch / idempotency)."""
import uuid

import pytest

from app.auth.jwt import create_access_token
from app.models.database import (
    CopyPosition,
    CopySignal,
    CopyStrategy,
    CopySubscriber,
    Instance,
    MT5Account,
    User,
)
from app.services.copy_trading_service import calculate_lot_size, dispatch_signals

_ip = [0]
_login = [1000001]
_ticket = [40001]


def _xff():
    _ip[0] += 1
    return f"203.0.113.{_ip[0] % 240 + 1}"


def _headers(**extra):
    h = {"X-Forwarded-For": _xff()}
    h.update(extra)
    return h


@pytest.fixture
def auth(client, db):
    """Real DB user (and its bearer token); accounts/instances created per test."""
    user = User(
        email=f"f4t{uuid.uuid4().hex[:8]}@example.com",
        username=f"f4t{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": "user"}
    )
    return user, token


def _make_instance(db, user):
    inst = Instance(
        id=f"inst-f4-{uuid.uuid4().hex[:8]}",
        name="F4 Copy",
        user_id=user.id,
        docker_container_id=f"f4-{uuid.uuid4().hex[:8]}",
        status="running",
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _make_account(db, user, instance=None):
    if instance is None:
        instance = _make_instance(db, user)
    _login[0] += 1
    acct = MT5Account(
        user_id=user.id,
        instance_id=instance.id,
        login=str(_login[0]),
        server="MetaQuotes-Demo",
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def _make_strategy(db, user, source_account, **kw):
    defaults = {"name": f"strat-{uuid.uuid4().hex[:8]}", "max_lots": 1.0}
    defaults.update(kw)
    strategy = CopyStrategy(
        user_id=user.id, source_account_id=source_account.id, **defaults
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


def _make_subscriber(db, user, strategy, target_account, **kw):
    defaults = {"lot_multiplier": 1.0, "lot_type": "fixed"}
    defaults.update(kw)
    sub = CopySubscriber(
        user_id=user.id,
        strategy_id=strategy.id,
        target_account_id=target_account.id,
        **defaults,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def _make_signal(db, strategy, ticket=None, symbol="XAUUSD", order_type="BUY",
                 volume=0.5, price=2400.0):
    if ticket is None:
        _ticket[0] += 1
        ticket = _ticket[0]
    signal = CopySignal(
        strategy_id=strategy.id,
        ticket=ticket,
        symbol=symbol,
        order_type=order_type,
        volume=volume,
        price=price,
        sl=None,
        tp=None,
        status="pending",
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


class FakeMT5Service:
    """Stands in for app.services.mt5_service.MT5Service.

    Each method name maps to a value in `_responses` (None -> falsy result,
    BaseException -> raise, anything else -> return). A list value is consumed
    one element per call (pop(0)) so tests can sequence failure then success.
    """

    _responses = {}
    _calls = []

    def __init__(self, instance_id):
        self.instance_id = instance_id

    def __getattr__(self, name):
        def _method(*args, **kwargs):
            FakeMT5Service._calls.append((name, args, kwargs))
            val = FakeMT5Service._responses.get(name)
            if isinstance(val, list):
                val = val.pop(0) if val else None
            if isinstance(val, BaseException):
                raise val
            return val

        return _method


@pytest.fixture(autouse=True)
def _fake_mt5(monkeypatch):
    FakeMT5Service._responses = {
        "place_order": {"ticket": 1001, "status": "filled"},
        "get_account_info": {"balance": 10000.0},
    }
    FakeMT5Service._calls = []
    monkeypatch.setattr(
        "app.services.copy_trading_service.MT5Service", FakeMT5Service
    )


def _place_order_calls():
    return [c for c in FakeMT5Service._calls if c[0] == "place_order"]


def _positions_for(db, signal):
    """CopyPosition rows created for a given signal (scoped by provider ticket)."""
    return (
        db.query(CopyPosition)
        .filter(CopyPosition.provider_ticket == signal.ticket)
        .all()
    )


# --- lot sizing -------------------------------------------------------------


def test_calculate_lot_size():
    assert calculate_lot_size(0.5, 2.0, "fixed") == 1.0
    assert calculate_lot_size(1.0, 1.0, "fixed") == 1.0
    assert calculate_lot_size(0.5, 10.0, "percentage", balance=5000.0) == 500.0
    # invalid inputs -> None
    assert calculate_lot_size(None, 2.0, "fixed") is None
    assert calculate_lot_size(0.0, 2.0, "fixed") is None
    assert calculate_lot_size(-1.0, 2.0, "fixed") is None
    assert calculate_lot_size(0.5, None, "fixed") is None
    assert calculate_lot_size(0.5, 0.0, "fixed") is None
    assert calculate_lot_size(0.5, 100.5, "fixed") is None
    assert calculate_lot_size(0.5, 10.0, "percentage", balance=None) is None
    # unknown lot_type -> ValueError
    with pytest.raises(ValueError):
        calculate_lot_size(0.5, 2.0, "bogus")


# --- dispatch ---------------------------------------------------------------


def test_dispatch_percentage_uses_account_balance(db, auth):
    user, _ = auth
    source = _make_account(db, user)
    target = _make_account(db, user)
    strategy = _make_strategy(db, user, source, max_lots=1000.0)
    _make_subscriber(
        db, user, strategy, target, lot_multiplier=2.0, lot_type="percentage"
    )
    signal = _make_signal(db, strategy)

    results = dispatch_signals(db, user_id=user.id)

    assert results[0]["status"] == "executed"
    assert FakeMT5Service._calls[0][0] == "get_account_info"
    assert _place_order_calls()[0][2]["volume"] == 200.0
    poss = _positions_for(db, signal)
    assert len(poss) == 1
    assert poss[0].volume == 200.0


def test_dispatch_caps_volume_to_max_lots(db, auth):
    user, _ = auth
    source = _make_account(db, user)
    target = _make_account(db, user)
    strategy = _make_strategy(db, user, source)  # max_lots defaults to 1.0
    _make_subscriber(
        db, user, strategy, target, lot_multiplier=100.0, lot_type="percentage"
    )
    signal = _make_signal(db, strategy)

    results = dispatch_signals(db, user_id=user.id)

    assert results[0]["status"] == "executed"
    assert _place_order_calls()[0][2]["volume"] == 1.0
    poss = _positions_for(db, signal)
    assert len(poss) == 1
    assert poss[0].volume == 1.0


def test_dispatch_is_idempotent(db, auth):
    user, _ = auth
    source = _make_account(db, user)
    target = _make_account(db, user)
    strategy = _make_strategy(db, user, source)
    _make_subscriber(db, user, strategy, target)
    signal = _make_signal(db, strategy)

    first = dispatch_signals(db, user_id=user.id)
    assert first[0]["status"] == "executed"

    # Force the signal back to pending: the existing CopyPosition guard must
    # prevent a second order.
    signal.status = "pending"
    db.commit()
    second = dispatch_signals(db, user_id=user.id)

    assert second[0]["status"] == "skipped"
    assert len(_positions_for(db, signal)) == 1
    assert len(_place_order_calls()) == 1


def test_dispatch_isolates_subscriber_failures(db, auth):
    user, _ = auth
    source = _make_account(db, user)
    target1 = _make_account(db, user)
    target2 = _make_account(db, user)
    strategy = _make_strategy(db, user, source)
    _make_subscriber(db, user, strategy, target1)
    _make_subscriber(db, user, strategy, target2)
    signal = _make_signal(db, strategy)
    # First subscriber's order blows up, the second succeeds.
    FakeMT5Service._responses["place_order"] = [
        RuntimeError("boom"),
        {"ticket": 1001, "status": "filled"},
    ]

    results = dispatch_signals(db, user_id=user.id)

    body = results[0]
    assert body["status"] == "partial"
    statuses = {o["status"] for o in body["subscribers"]}
    assert "error" in statuses
    assert "executed" in statuses
    assert len(_positions_for(db, signal)) == 1
    db.refresh(signal)
    assert signal.status == "partial"
    assert signal.error_message is not None


def test_dispatch_consumes_pending_signals(db, auth):
    user, _ = auth
    source = _make_account(db, user)
    target = _make_account(db, user)
    strategy = _make_strategy(db, user, source)
    _make_subscriber(db, user, strategy, target)
    _make_signal(db, strategy)

    first = dispatch_signals(db, user_id=user.id)
    assert first[0]["status"] == "executed"
    assert dispatch_signals(db, user_id=user.id) == []


# --- API --------------------------------------------------------------------


def test_dispatch_endpoint_happy_path(client, db, auth):
    user, token = auth
    source = _make_account(db, user)
    target = _make_account(db, user)

    resp = client.post(
        "/api/v1/copy/strategies",
        json={"name": "f4-strategy", "source_account_id": source.id},
        headers=_headers(Authorization=f"Bearer {token}"),
    )
    assert resp.status_code == 200
    strategy_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/copy/subscribers",
        json={
            "strategy_id": strategy_id,
            "target_account_id": target.id,
            "lot_multiplier": 2.0,
            "lot_type": "fixed",
        },
        headers=_headers(Authorization=f"Bearer {token}"),
    )
    assert resp.status_code == 200

    strategy = (
        db.query(CopyStrategy).filter(CopyStrategy.id == strategy_id).first()
    )
    signal = _make_signal(db, strategy)

    resp = client.post(
        "/api/v1/copy/dispatch",
        headers=_headers(Authorization=f"Bearer {token}"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dispatched"] == 1
    assert body["results"][0]["status"] == "executed"
    assert len(_place_order_calls()) == 1
    assert len(_positions_for(db, signal)) == 1
