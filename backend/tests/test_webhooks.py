"""B6 tests for the webhook API (app.api.webhooks).

``/receive`` is a public NOWPayments-style IPN endpoint: the body must be
signed with ``X-NowPayments-Sig`` (HMAC-SHA512 over the raw body using
``settings.NOWPAYMENTS_IPN_SECRET``). ``/configure``, ``GET ""``,
``DELETE /{id}`` and ``POST /test/{id}`` require a bearer token; the config
secret is stored encrypted and never returned by the list endpoint. All data
is seeded per-test with unique users and unique client IPs.
"""
import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace

from app.auth.jwt import create_access_token
from app.config import settings
from app.main import app
from app.models.database import User, WebhookConfig


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


def _plain_headers():
    return {"X-Forwarded-For": _xff()}


def _make_user(db):
    username = f"b6w{uuid.uuid4().hex[:8]}"
    user = User(
        email=f"{username}@example.com",
        username=username,
        hashed_password="x",
        full_name="B6 Webhooks",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _sig(raw: bytes) -> str:
    return hmac.new(
        settings.NOWPAYMENTS_IPN_SECRET.encode(), raw, hashlib.sha512
    ).hexdigest()


def _make_config(db, user_id, *, name="cfg", url="http://8.8.8.8/webhook", secret=None, events=("order.filled",)):
    cfg = WebhookConfig(
        user_id=user_id,
        name=name,
        url=url,
        secret=secret,
        events=json.dumps(list(events)),
        is_active=True,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def _url(path):
    return f"/api/v1/webhooks{path}"


def _receive(client, raw: bytes, signature: str):
    return client.post(
        _url("/receive"),
        content=raw,
        headers={**_plain_headers(), "X-NowPayments-Sig": signature},
    )


# --- POST /receive (public, signature-gated) ----------------------------------


def test_receive_empty_body_400(client, db):
    resp = _receive(client, b"", _sig(b""))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid webhook payload"}


def test_receive_missing_signature_401(client, db):
    resp = client.post(_url("/receive"), content=b"{}", headers=_plain_headers())
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid signature"}


def test_receive_invalid_signature_401(client, db):
    resp = _receive(client, b'{"symbol": "EURUSD"}', "deadbeef")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid signature"}


def test_receive_valid_no_symbol_ignored(client, db):
    resp = _receive(client, b'{"action": "buy"}', _sig(b'{"action": "buy"}'))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored", "reason": "no symbol"}


def test_receive_valid_signal(client, db):
    raw = b'{"symbol": "EURUSD", "action": "buy", "volume": 0.5, "price": 1.08}'
    resp = _receive(client, raw, _sig(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "received"
    assert body["signal"] == {
        "symbol": "EURUSD",
        "action": "BUY",
        "volume": 0.5,
        "price": 1.08,
    }


def test_receive_alias_fields(client, db):
    # ticker/direction/qty are accepted aliases; defaults fill the rest.
    raw = b'{"ticker": "XAUUSD", "direction": "sell", "qty": 2}'
    resp = _receive(client, raw, _sig(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal"]["symbol"] == "XAUUSD"
    assert body["signal"]["action"] == "SELL"
    assert body["signal"]["volume"] == 2.0
    assert body["signal"]["price"] == 0


def test_receive_invalid_json_400(client, db):
    raw = b'{"symbol": '
    resp = _receive(client, raw, _sig(raw))
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid webhook payload"}


# --- POST /configure ----------------------------------------------------------


def test_configure_requires_auth(client, db):
    resp = client.post(
        _url("/configure"),
        json={"name": "x", "url": "http://8.8.8.8/webhook", "events": []},
        headers=_plain_headers(),
    )
    assert resp.status_code == 401


def test_configure_invalid_url_400(client, db):
    user = _make_user(db)
    resp = client.post(
        _url("/configure"),
        json={"name": "x", "url": "ftp://8.8.8.8/webhook", "events": []},
        headers=_headers(user.id),
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid webhook URL"}


def test_configure_success(client, db):
    user = _make_user(db)
    resp = client.post(
        _url("/configure"),
        json={
            "name": "alerts",
            "url": "http://8.8.8.8/webhook",
            "events": ["order.filled", "position.closed"],
        },
        headers=_headers(user.id),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "created"
    assert isinstance(body["id"], int)

    cfg = db.query(WebhookConfig).filter(WebhookConfig.id == body["id"]).first()
    assert cfg is not None
    assert cfg.user_id == user.id
    assert cfg.name == "alerts"
    assert cfg.secret is None
    assert cfg.is_active is True


# --- GET "" -------------------------------------------------------------------


def test_list_requires_auth(client, db):
    resp = client.get(_url(""), headers=_plain_headers())
    assert resp.status_code == 401


def test_list_empty(client, db):
    user = _make_user(db)
    resp = client.get(_url(""), headers=_headers(user.id))
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_returns_own_only_no_secret(client, db):
    user_a = _make_user(db)
    user_b = _make_user(db)
    _make_config(db, user_a.id, name="a-cfg", secret="top-secret")

    resp = client.get(_url(""), headers=_headers(user_a.id))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "a-cfg"
    assert body[0]["events"] == ["order.filled"]
    assert body[0]["is_active"] is True
    assert "secret" not in body[0]

    resp_b = client.get(_url(""), headers=_headers(user_b.id))
    assert resp_b.status_code == 200
    assert resp_b.json() == []


# --- DELETE /{id} -------------------------------------------------------------


def test_delete_requires_auth(client, db):
    resp = client.delete(_url("/1"), headers=_plain_headers())
    assert resp.status_code == 401


def test_delete_missing_404(client, db):
    user = _make_user(db)
    resp = client.delete(_url("/999999"), headers=_headers(user.id))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Webhook not found"}


def test_delete_own_success_then_404(client, db):
    user = _make_user(db)
    cfg = _make_config(db, user.id)

    resp = client.delete(_url(f"/{cfg.id}"), headers=_headers(user.id))
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}

    resp2 = client.delete(_url(f"/{cfg.id}"), headers=_headers(user.id))
    assert resp2.status_code == 404


def test_delete_other_users_404(client, db):
    user_a = _make_user(db)
    user_b = _make_user(db)
    cfg = _make_config(db, user_a.id)

    resp = client.delete(_url(f"/{cfg.id}"), headers=_headers(user_b.id))
    assert resp.status_code == 404

    # still present for the owner
    assert db.query(WebhookConfig).filter(WebhookConfig.id == cfg.id).count() == 1


# --- POST /test/{id} ----------------------------------------------------------


def test_test_webhook_requires_auth(client, db):
    resp = client.post(_url("/test/1"), headers=_plain_headers())
    assert resp.status_code == 401


def test_test_webhook_missing_404(client, db):
    user = _make_user(db)
    resp = client.post(_url("/test/999999"), headers=_headers(user.id))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Webhook not found"}


def test_test_webhook_success(client, db, monkeypatch):
    user = _make_user(db)
    cfg = _make_config(db, user.id)

    monkeypatch.setattr(
        "httpx.post", lambda *a, **k: SimpleNamespace(status_code=200)
    )
    resp = client.post(_url(f"/test/{cfg.id}"), headers=_headers(user.id))
    assert resp.status_code == 200
    assert resp.json() == {"status": "success", "response_code": 200}


def test_test_webhook_delivery_error(client, db, monkeypatch):
    user = _make_user(db)
    cfg = _make_config(db, user.id)

    def _boom(*a, **k):
        raise RuntimeError("delivery failed")

    monkeypatch.setattr("httpx.post", _boom)
    resp = client.post(_url(f"/test/{cfg.id}"), headers=_headers(user.id))
    assert resp.status_code == 200
    assert resp.json() == {"status": "error", "message": "Webhook delivery failed"}
