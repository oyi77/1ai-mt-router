import pytest
import os

os.environ["ENCRYPTION_KEY"] = "XAqbCaYA-A2zWyRsyVZd6r6Rv2ckUSw7mqua2R1m-HM="
os.environ["JWT_SECRET"] = "b6-test-jwt-secret-0123456789abcdef"
os.environ["DATABASE_URL"] = "sqlite:////tmp/mt5router-b6-test.db"
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_WEBHOOK_SECRET"] = ""
# Trust X-Forwarded-For in tests so per-test fake client IPs are honoured by
# the rate limiter (TestClient's peer host is "testserver").
os.environ["TRUSTED_PROXIES"] = "*"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base, User
from app.core.database import get_db
from app.auth.jwt import get_current_user, create_access_token

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_user(db):
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password="$2b$12$LQv3c1yqBo9SkvXS7mNGeOQWjwQwQwQwQwQwQwQwQwQwQwQwQwQw",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_token(test_user):
    return create_access_token(data={"sub": str(test_user.id)})


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    """Drop shared RateLimitMiddleware state before each test.

    The middleware instance is created once at app import (main.py adds it via
    add_middleware) and persists across tests in the same process. Each
    TestClient context runs the app on its own asyncio event loop, so the
    middleware's cached asyncio Redis client can be bound to a previous test's
    loop and die with it ("Event loop is closed" on the next test). Resetting
    here forces a fresh client on the current loop and clears the in-memory
    bucket, making tests order-independent. redis_service's module-level client
    is dropped for the same reason.
    """
    from app.middleware.rate_limit import RateLimitMiddleware

    stack = app.middleware_stack
    while stack is not None and not isinstance(stack, RateLimitMiddleware):
        stack = getattr(stack, "app", None)
    if isinstance(stack, RateLimitMiddleware):
        stack._redis = None
        stack._last_redis_attempt = 0.0
        stack.requests.clear()
    from app.services import redis_service

    redis_service.redis_client = None
    yield
