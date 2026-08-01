"""Rate-limit middleware behaviour beyond the core 429 contract.

test_regressions.test_rate_limit_returns_429 pins the primary contract
(HTTP 429 + detail + headers past the per-minute limit). This file covers
the surrounding semantics the middleware promises:

1. Per-client accounting — requests from one IP never consume another IP's
   budget (the middleware keys on the client IP, not a global counter).
2. Success-path headers — well-formed X-RateLimit-Limit / -Remaining on
   200 responses.
3. Fail-open to the in-memory window when Redis is unreachable — the HTTP
   contract is identical, so the service keeps rate limiting during a
   Redis outage.

Like the regression suite, each test uses a fresh unique client IP via
X-Forwarded-For (198.51.100.x, TEST-NET-1, never routed) so buckets never
leak across tests, and the autouse conftest fixture resets the shared
middleware state (cached Redis client, in-memory counters) before every
test. The assertions hold on both the Redis and in-memory paths, so the
suite is hermetic and does not depend on a running Redis.
"""

import secrets

import pytest

LIMIT = 100  # must match settings.RATE_LIMIT_PER_MINUTE


def _unique_ip() -> str:
    return f"198.51.100.{secrets.randbelow(200) + 1}"


def _hit_until_429(client, ip: str, max_hits: int = LIMIT + 1):
    """Send requests from one IP until the middleware returns 429.

    With a limit of 100, the (limit+1)-th request is guaranteed to be
    rejected on both the Redis and in-memory paths, so max_hits = 101 is
    always sufficient.
    """
    headers = {"X-Forwarded-For": ip}
    resp = None
    seen = set()
    for _ in range(max_hits):
        resp = client.get("/health", headers=headers)
        if resp.status_code == 429:
            break
        seen.add(resp.status_code)
    else:
        pytest.fail(
            f"expected HTTP 429 within {max_hits} requests; "
            f"got statuses {sorted(seen)}"
        )
    return resp


def test_different_ips_count_independently(client):
    """Exhausting IP A's budget must not affect a fresh IP B."""
    ip_a = _unique_ip()
    resp = _hit_until_429(client, ip_a)
    assert resp.status_code == 429
    assert resp.json() == {"detail": "Rate limit exceeded"}

    # A different IP starts with a clean bucket: first request succeeds.
    resp_b = client.get("/health", headers={"X-Forwarded-For": _unique_ip()})
    assert resp_b.status_code == 200
    assert resp_b.headers.get("X-RateLimit-Limit") == str(LIMIT)
    assert resp_b.headers.get("X-RateLimit-Remaining") is not None


def test_success_headers_report_limit_and_remaining(client):
    """A successful request carries well-formed X-RateLimit headers."""
    resp = client.get("/health", headers={"X-Forwarded-For": _unique_ip()})
    assert resp.status_code == 200
    assert resp.headers.get("X-RateLimit-Limit") == str(LIMIT)
    remaining = resp.headers.get("X-RateLimit-Remaining")
    assert remaining is not None
    assert remaining.isdigit()
    assert 0 <= int(remaining) <= LIMIT


def test_redis_failure_falls_back_to_memory(client, monkeypatch):
    """A down Redis must not stop rate limiting: fail open to memory."""
    from app.middleware.rate_limit import redis_service

    calls = []

    async def _broken_init_redis():
        calls.append(1)
        raise RuntimeError("redis down for test")

    monkeypatch.setattr(redis_service, "init_redis", _broken_init_redis)

    resp = _hit_until_429(client, _unique_ip())
    assert resp.status_code == 429
    assert resp.json() == {"detail": "Rate limit exceeded"}

    # Prove the fallback path actually ran: init_redis was attempted and
    # failed, and the retry throttle (5s) kept later requests on memory.
    assert calls, "expected at least one init_redis attempt before fallback"
