"""Smoke tests for app construction + middleware wiring (F11).

Pins the behaviour the app-main wiring must keep after the logging /
middleware-ordering fix:

1. The app imports and boots via TestClient; plain routes respond normally
   (``/health`` and ``/api/health``).
2. ``RequestIdMiddleware`` is wired: an inbound ``X-Request-ID`` is echoed on
   the response, and one is generated when absent.
3. CORS is the OUTERMOST middleware, so error responses produced inside the
   stack (the rate limiter's 429) still carry ``Access-Control-Allow-Origin``
   — a browser-facing requirement. This is the regression the F11 reorder
   fixed: previously RateLimitMiddleware was added last (= outermost) and its
   bare ``JSONResponse`` 429s carried no CORS headers.

The rate-limit test uses a unique ``X-Forwarded-For`` client IP (198.51.100.x,
TEST-NET-1, never routed) so it never pollutes another test's bucket, and the
autouse conftest fixture resets the shared middleware state beforehand.
"""

import secrets

LIMIT = 100  # must match settings.RATE_LIMIT_PER_MINUTE


def _unique_ip() -> str:
    return f"198.51.100.{secrets.randbelow(200) + 1}"


def test_health_route_returns_200(client):
    """A plain route still boots and returns normally through the stack."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "redirect": "/api/health"}


def test_api_health_route_returns_200(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"]


def test_request_id_header_is_echoed(client):
    """Inbound X-Request-ID is passed through onto the response."""
    resp = client.get("/health", headers={"X-Request-ID": "smoke-req-123"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == "smoke-req-123"


def test_request_id_is_generated_when_absent(client):
    """A response always carries an X-Request-ID, generated if not sent."""
    resp = client.get("/health")
    assert resp.status_code == 200
    request_id = resp.headers.get("X-Request-ID")
    assert request_id, "expected a generated X-Request-ID on the response"


def test_cors_headers_present_on_rate_limit_429(client):
    """429 responses carry CORS headers (CORSMiddleware is outermost)."""
    ip = _unique_ip()
    headers = {"X-Forwarded-For": ip, "Origin": "https://example.com"}
    resp = None
    for _ in range(LIMIT + 1):
        resp = client.get("/health", headers=headers)
        if resp.status_code == 429:
            break
    assert resp is not None
    assert resp.status_code == 429
    assert resp.json() == {"detail": "Rate limit exceeded"}
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"
