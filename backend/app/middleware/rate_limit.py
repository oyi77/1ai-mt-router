from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging
from collections import defaultdict
from typing import Optional

from app.config import settings
from app.services import redis_service

logger = logging.getLogger(__name__)

# How long to wait before retrying a failed Redis connection. Prevents a down
# Redis from adding latency to every request (fail-open to in-memory rate
# limiting in the meantime).
REDIS_RETRY_INTERVAL = 5.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client rate limiting.

    In production, uses Redis (fixed 60s window) and fails closed (503) if
    Redis is unreachable, so the shared limit cannot silently diverge across
    workers. Outside production, uses the per-process in-memory sliding
    window (Redis is still attempted and cached so the fail-open path is
    exercised and a connection is warm for production).
    """

    def __init__(self, app, requests_per_minute: Optional[int] = None):
        super().__init__(app)
        self.requests_per_minute = (
            settings.RATE_LIMIT_PER_MINUTE
            if requests_per_minute is None
            else requests_per_minute
        )
        self.requests = defaultdict(list)
        self._redis = None
        self._last_redis_attempt = 0.0

    @staticmethod
    def _client_ip(request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for")
        trusted = settings.trusted_proxies
        # Only honour X-Forwarded-For when the socket peer is a trusted proxy
        # (or trust is configured open with "*"); otherwise the header can be
        # spoofed by an attacker to exhaust another client's rate-limit bucket.
        if forwarded and ("*" in trusted or peer in trusted):
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = peer
        return client_ip or "unknown"

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        now = time.time()
        if now - self._last_redis_attempt < REDIS_RETRY_INTERVAL:
            return None
        self._last_redis_attempt = now
        try:
            client = await redis_service.init_redis()
            await client.ping()
            self._redis = client
            logger.info("Rate limiting using Redis")
            return client
        except Exception as exc:
            logger.warning(f"Redis unavailable, using in-memory rate limiting: {exc}")
            return None

    async def _dispatch_redis(self, request, call_next, client, client_ip, limit):
        key = f"rate_limit:{client_ip}"
        current = await client.incr(key)
        if current == 1:
            await client.expire(key, 60)

        if current > limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(limit - current)
        return response

    async def _dispatch_memory(self, request, call_next, client_ip, limit):
        now = time.time()
        self.requests[client_ip] = [
            t for t in self.requests[client_ip] if now - t < 60
        ]

        if len(self.requests[client_ip]) >= limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        self.requests[client_ip].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(
            limit - len(self.requests[client_ip])
        )
        return response

    async def dispatch(self, request: Request, call_next):
        client_ip = self._client_ip(request)
        limit = self.requests_per_minute

        if settings.ENV != "production":
            # Development/test run a single process, so the per-process
            # in-memory window is equivalent to Redis for one worker and
            # keeps the shared-Redis counters from drifting across tests.
            # Redis is still attempted (and cached) so the fail-open path
            # is exercised and a connection is warm for production.
            await self._get_redis()
            return await self._dispatch_memory(
                request, call_next, client_ip, limit
            )

        client = await self._get_redis()
        if client is None:
            # In production the per-process in-memory window would diverge
            # across workers, silently weakening the rate limit, so a Redis
            # outage fails closed instead of downgrading to per-process memory.
            return JSONResponse(
                status_code=503,
                content={"detail": "Rate limiting temporarily unavailable"},
            )
        return await self._dispatch_redis(
            request, call_next, client, client_ip, limit
        )
