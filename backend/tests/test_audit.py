"""Tests for ``app.core.audit`` IP attribution (trusted-proxy aware)."""

from fastapi import Request

from app.config import settings
from app.core.audit import log_user_action
from app.models.database import AuditLog


def _make_request(client_host, headers=None):
    """Build a minimal FastAPI Request with a given socket peer and headers."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (name.lower().encode(), value.encode())
            for name, value in (headers or {}).items()
        ],
        "client": (client_host, 12345) if client_host is not None else None,
        "server": ("testserver", 80),
    }
    return Request(scope)


def _ip_for(db, request):
    entry = log_user_action(
        db,
        user_id=1,
        action="test.audit",
        resource_type="test",
        request=request,
    )
    return entry.ip_address


def test_direct_request_records_socket_peer(db):
    """Without X-Forwarded-For the socket peer is recorded."""
    request = _make_request("10.0.0.9")
    assert _ip_for(db, request) == "10.0.0.9"


def test_forwarded_for_honoured_with_star_trust(db):
    """With TRUSTED_PROXIES='*' the X-Forwarded-For value wins."""
    request = _make_request("testserver", headers={"X-Forwarded-For": "1.2.3.4"})
    assert settings.trusted_proxies == ["*"]
    assert _ip_for(db, request) == "1.2.3.4"


def test_forwarded_for_honoured_when_peer_is_trusted(db, monkeypatch):
    """With the peer listed in TRUSTED_PROXIES the forwarded value wins."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "203.0.113.5")
    request = _make_request(
        "203.0.113.5", headers={"X-Forwarded-For": "1.2.3.4"}
    )
    assert _ip_for(db, request) == "1.2.3.4"


def test_forwarded_for_uses_first_hop(db, monkeypatch):
    """Only the left-most X-Forwarded-For hop is used for a trusted peer."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "*")
    request = _make_request(
        "testserver",
        headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.5, 192.168.1.1"},
    )
    assert _ip_for(db, request) == "1.2.3.4"


def test_forwarded_for_ignored_for_untrusted_peer(db, monkeypatch):
    """An untrusted peer cannot spoof its IP via X-Forwarded-For."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "192.168.1.10")
    request = _make_request(
        "203.0.113.7", headers={"X-Forwarded-For": "1.2.3.4"}
    )
    assert _ip_for(db, request) == "203.0.113.7"


def test_request_without_client_records_unknown(db):
    """A request with no client info falls back to 'unknown'."""
    request = _make_request(None)
    assert _ip_for(db, request) == "unknown"


def test_request_without_client_ignores_header_for_untrusted_peer(db, monkeypatch):
    """With no peer and no trust configured, X-Forwarded-For is ignored."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "192.168.1.10")
    request = _make_request(None, headers={"X-Forwarded-For": "1.2.3.4"})
    assert _ip_for(db, request) == "unknown"


def test_no_request_keeps_ip_none(db):
    """Without a request object no IP is recorded."""
    entry = log_user_action(db, user_id=1, action="test.audit", request=None)
    assert entry.ip_address is None


def test_entry_is_persisted(db):
    """The audit row is committed and queryable."""
    request = _make_request("10.0.0.9")
    log_user_action(
        db,
        user_id=1,
        action="test.audit",
        resource_type="test",
        resource_id="42",
        request=request,
    )
    row = (
        db.query(AuditLog)
        .filter(AuditLog.action == "test.audit")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.ip_address == "10.0.0.9"
    assert row.resource_id == "42"
