from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
import asyncio
import logging
import os
from typing import Optional

import bcrypt

from app.config import settings
from app.api import (
    admin,
    instances,
    vnc,
    trading,
    monitoring,
    auth,
    notifications,
    users,
    servers,
    billing,
    payments,
    accounts,
    copytrading,
    statistics,
    webhooks,
)
from app.models.database import Base
from app.core.database import engine, SessionLocal
from app.core.http import register_exception_handlers
from app.core.logging import setup_logging, RequestIdMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.services.ssh_service import init_ssh_service
from app.services.billing_service import init_billing_service
from app.services.nowpayments_service import init_nowpayments_service
from app.services.payment_service import init_payment_service
from app.services.auth_enhancement_service import init_auth_enhancement_service
from app.services.alert_engine import alert_engine
from app.services.notification_service import notification_service
from app.services.metrics_collector import (
    start_metrics_collector,
    stop_metrics_collector,
)

# Structured JSON logging + request-id support (replaces logging.basicConfig).
# setup_logging is idempotent and safe to call at import time; it reconfigures
# the root logger once instead of relying on basicConfig.
setup_logging()
logger = logging.getLogger(__name__)

# Queue consumed by the notification dispatch loop. Producers (alert engine,
# trading events) put (event, data, channels) tuples here so dispatch never
# blocks the producer.
_notification_queue: Optional[asyncio.Queue] = None


async def _webhook_dispatch_loop(queue: asyncio.Queue):
    while True:
        try:
            event, data, channels = await queue.get()
            await notification_service.notify(event, data, channels)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"Notification dispatch failed: {exc}")


async def _alert_engine_loop():
    # Ticker loop keeping the alert engine alive on the cooldown cadence.
    # Actual rule evaluation (market data, account snapshots) is owned by the
    # alert subsystem; this just wakes the engine so it can run checks.
    while alert_engine.running:
        try:
            await asyncio.sleep(settings.ALERT_COOLDOWN)
        except asyncio.CancelledError:
            raise


def _bootstrap_admin() -> None:
    """Create the first-run admin account when ADMIN_* settings are configured.

    No-op unless all three of ADMIN_USERNAME / ADMIN_EMAIL / ADMIN_PASSWORD
    are set. The account is created once and never overwritten on later
    startups.
    """
    if not (
        settings.ADMIN_USERNAME and settings.ADMIN_EMAIL and settings.ADMIN_PASSWORD
    ):
        return
    from app.models.database import User, UserRole

    db = SessionLocal()
    try:
        existing = (
            db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
        )
        if existing is not None:
            return
        db.add(
            User(
                email=settings.ADMIN_EMAIL,
                username=settings.ADMIN_USERNAME,
                hashed_password=bcrypt.hashpw(
                    settings.ADMIN_PASSWORD.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8"),
                full_name="Administrator",
                role=UserRole.ADMIN.value,
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
        logger.info(f"Created admin account '{settings.ADMIN_USERNAME}'")
    except Exception:
        db.rollback()
        logger.exception("Failed to bootstrap admin account")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _bootstrap_admin()
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    if settings.ENCRYPTION_KEY:
        init_ssh_service(settings.ENCRYPTION_KEY)
        logger.info("SSH service initialized")

    if settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET:
        init_billing_service(settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET)
        logger.info("Billing service initialized")

    if settings.NOWPAYMENTS_API_KEY:
        init_nowpayments_service(
            settings.NOWPAYMENTS_API_KEY,
            settings.NOWPAYMENTS_IPN_SECRET,
            settings.NOWPAYMENTS_SANDBOX,
        )
        logger.info("NOWPayments service initialized")

    if settings.PAYMENT_API_KEY:
        init_payment_service(
            settings.PAYMENT_API_KEY,
            settings.PAYMENT_BASE_URL,
            settings.PAYMENT_GATEWAY,
            settings.PAYMENT_WEBHOOK_SECRET,
        )
        logger.info("1ai-payment service initialized")

    init_auth_enhancement_service(
        smtp_host=settings.SMTP_HOST,
        smtp_port=settings.SMTP_PORT,
        smtp_user=settings.SMTP_USER,
        smtp_password=settings.SMTP_PASSWORD,
        from_email=settings.FROM_EMAIL,
        base_url=settings.BASE_URL,
    )
    logger.info("Auth enhancement service initialized")

    start_metrics_collector(interval=settings.METRICS_INTERVAL)
    logger.info("Metrics collector started")

    global _notification_queue
    _notification_queue = asyncio.Queue()
    _dispatch_task = asyncio.create_task(_webhook_dispatch_loop(_notification_queue))
    alert_engine.start()
    _alert_task = asyncio.create_task(_alert_engine_loop())
    logger.info("Notification dispatcher and alert engine started")

    yield
    logger.info("Shutting down...")
    _dispatch_task.cancel()
    _alert_task.cancel()
    for task in (_dispatch_task, _alert_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    alert_engine.stop()
    stop_metrics_collector()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Starlette applies middleware LIFO: the LAST add_middleware call ends up
# OUTERMOST. CORS must be outermost so error responses (e.g. the rate
# limiter's 429) still carry Access-Control-Allow-* headers for browsers.
# Request-id first (innermost), rate limit middle, CORS last (outermost).
origins = settings.cors_origins
app.add_middleware(RequestIdMiddleware)

app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(instances.router, prefix="/api/v1/instances", tags=["Instances"])
app.include_router(vnc.router, prefix="/api/v1/vnc", tags=["VNC"])
app.include_router(trading.router, prefix="/api/v1/trading", tags=["Trading"])
app.include_router(monitoring.router, prefix="/api/v1/monitoring", tags=["Monitoring"])
app.include_router(
    notifications.router, prefix="/api/v1/notifications", tags=["Notifications"]
)
app.include_router(servers.router, prefix="/api/v1/servers", tags=["Servers"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(
    payments.router, prefix="/api/v1/payments", tags=["Payments"]
)
app.include_router(accounts.router, prefix="/api/v1/accounts", tags=["MT5 Accounts"])
app.include_router(copytrading.router, prefix="/api/v1/copy", tags=["Copy Trading"])
app.include_router(
    statistics.router, prefix="/api/v1/stats", tags=["Trading Statistics"]
)
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/health")
async def health_redirect():
    return {"status": "ok", "redirect": "/api/health"}


@app.get("/api/v1/info")
async def info():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "mt5_image": settings.MT5_IMAGE,
        "features": [
            "instances",
            "vnc",
            "trading",
            "monitoring",
            "notifications",
            "accounts",
        ],
    }


FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist"
)

if os.path.exists(FRONTEND_DIR):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")),
        name="assets",
    )

    @app.get("/favicon.svg")
    @app.get("/vite.svg")
    async def serve_favicon():
        favicon_path = os.path.join(FRONTEND_DIR, "favicon.svg")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path)
        return {"detail": "Not Found"}

    @app.get("/{full_path:path}")
    async def serve_frontend(request: Request, full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # Resolve symlinks / .. before serving so requests cannot escape the
        # frontend build directory (path traversal).
        resolved_root = os.path.realpath(FRONTEND_DIR)
        file_path = os.path.realpath(os.path.join(FRONTEND_DIR, full_path))
        if os.path.commonpath([resolved_root, file_path]) != resolved_root:
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        if full_path and os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)

        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    logger.info(f"Frontend static files mounted from {FRONTEND_DIR}")
else:
    logger.warning(f"Frontend directory not found at {FRONTEND_DIR}")
