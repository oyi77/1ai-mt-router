from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    API_ONLY = "api_only"


class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(String(20), default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Email verification
    verification_token = Column(String(255))
    verification_token_expires = Column(DateTime)

    # Password reset
    reset_token = Column(String(255))
    reset_token_expires = Column(DateTime)

    # Two-factor authentication
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(Text)

    # Phone verification
    phone_number = Column(String(20))
    phone_verified = Column(Boolean, default=False)

    # Login security
    last_login = Column(DateTime)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime)

    api_keys = relationship("ApiKey", back_populates="user")
    instances = relationship("Instance", back_populates="owner")
    accounts = relationship("MT5Account", back_populates="owner")
    alerts = relationship("Alert", back_populates="user")
    ssh_servers = relationship("SSHServer", back_populates="owner")
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    invoices = relationship("Invoice", back_populates="user")
    strategies = relationship("CopyStrategy", back_populates="user")
    subscribers = relationship("CopySubscriber", back_populates="user")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    name = Column(String(100))
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    permissions = Column(Text)
    is_active = Column(Boolean, default=True)
    rate_limit = Column(Integer, default=100)
    last_used = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="api_keys")


class Instance(Base):
    __tablename__ = "instances"

    id = Column(String(50), primary_key=True)
    name = Column(String(100))
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    server_id = Column(Integer, ForeignKey("ssh_servers.id"), index=True)
    docker_container_id = Column(String(100))
    status = Column(String(20))
    rpyc_port = Column(Integer)
    vnc_port = Column(Integer)
    config = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="instances")
    server = relationship("SSHServer", back_populates="instances")
    account = relationship("MT5Account", back_populates="instance", uselist=False)


class MT5Account(Base):
    __tablename__ = "mt5_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    instance_id = Column(String(50), ForeignKey("instances.id"), index=True)

    login = Column(String(50))
    server = Column(String(100))
    broker = Column(String(100))
    account_name = Column(String(255))
    is_demo = Column(Boolean, default=True)

    encrypted_password = Column(Text)

    connection_status = Column(String(20), default="disconnected")
    connection_error = Column(Text)
    last_connected = Column(DateTime)
    last_disconnected = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="accounts")
    instance = relationship("Instance", back_populates="account")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    instance_id = Column(String(50), index=True)
    alert_type = Column(String(50))
    condition = Column(Text)
    channel = Column(String(50))
    is_active = Column(Boolean, default=True)
    last_triggered = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="alerts")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer)
    action = Column(String(100))
    resource_type = Column(String(50))
    resource_id = Column(String(100))
    details = Column(Text)
    ip_address = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    api_key_id = Column(Integer, index=True)
    endpoint = Column(String(200))
    method = Column(String(10))
    response_time_ms = Column(Integer)
    status_code = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class SSHServer(Base):
    __tablename__ = "ssh_servers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String(100), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=22)
    username = Column(String(100), nullable=False)
    encrypted_private_key = Column(Text)
    encrypted_password = Column(Text)
    use_key_auth = Column(Boolean, default=True)
    docker_socket = Column(String(255), default="/var/run/docker.sock")
    is_active = Column(Boolean, default=True)
    last_connected = Column(DateTime)
    last_health_check = Column(DateTime)
    health_status = Column(String(20), default="unknown")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="ssh_servers")
    instances = relationship("Instance", back_populates="server")
    metrics = relationship("ServerMetrics", back_populates="server")


class ServerMetrics(Base):
    __tablename__ = "server_metrics"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("ssh_servers.id"), index=True)
    cpu_percent = Column(Float)
    memory_total_mb = Column(Float)
    memory_used_mb = Column(Float)
    disk_total_gb = Column(Float)
    disk_used_gb = Column(Float)
    network_rx_mb = Column(Float)
    network_tx_mb = Column(Float)
    docker_containers_total = Column(Integer)
    docker_containers_running = Column(Integer)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    server = relationship("SSHServer", back_populates="metrics")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    tier = Column(String(20), default=SubscriptionTier.FREE)
    stripe_customer_id = Column(String(255))
    stripe_subscription_id = Column(String(255))
    stripe_price_id = Column(String(255))
    status = Column(
        String(20), default="active"
    )  # active, canceled, past_due, trialing
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    cancel_at_period_end = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="subscription")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    stripe_invoice_id = Column(String(255))
    amount_cents = Column(Integer)
    currency = Column(String(3), default="usd")
    status = Column(String(20))  # paid, open, void, etc.
    invoice_url = Column(String(500))
    pdf_url = Column(String(500))
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="invoices")


class CopyStrategy(Base):
    __tablename__ = "copy_strategies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    source_account_id = Column(Integer, ForeignKey("mt5_accounts.id"), index=True)

    is_active = Column(Boolean, default=True)
    symbol_filter = Column(Text)
    max_lots = Column(Float, default=1.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="strategies")
    source_account = relationship("MT5Account")
    subscribers = relationship("CopySubscriber", back_populates="strategy")
    signals = relationship("CopySignal", back_populates="strategy")


class CopySubscriber(Base):
    __tablename__ = "copy_subscribers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    strategy_id = Column(Integer, ForeignKey("copy_strategies.id"), index=True)
    target_account_id = Column(Integer, ForeignKey("mt5_accounts.id"), index=True)

    is_active = Column(Boolean, default=True)
    lot_multiplier = Column(Float, default=1.0)
    lot_type = Column(String(20), default="fixed")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="subscribers")
    strategy = relationship("CopyStrategy", back_populates="subscribers")
    target_account = relationship("MT5Account")
    positions = relationship("CopyPosition", back_populates="subscriber")


class CopySignal(Base):
    __tablename__ = "copy_signals"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("copy_strategies.id"), index=True)

    ticket = Column(Integer)
    symbol = Column(String(50))
    order_type = Column(String(20))
    volume = Column(Float)
    price = Column(Float)
    sl = Column(Float)
    tp = Column(Float)

    status = Column(String(20), default="pending")
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    strategy = relationship("CopyStrategy", back_populates="signals")


class CopyPosition(Base):
    __tablename__ = "copy_positions"

    id = Column(Integer, primary_key=True, index=True)
    subscriber_id = Column(Integer, ForeignKey("copy_subscribers.id"), index=True)

    provider_ticket = Column(Integer)
    subscriber_ticket = Column(Integer)
    symbol = Column(String(50))
    order_type = Column(String(20))
    volume = Column(Float)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)
    pnl = Column(Float)

    subscriber = relationship("CopySubscriber", back_populates="positions")


class InstanceMetrics(Base):
    __tablename__ = "instance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    instance_id = Column(String(100), index=True, nullable=False)
    instance_name = Column(String(255))
    cpu_percent = Column(Float, default=0)
    memory_usage_mb = Column(Float, default=0)
    memory_limit_mb = Column(Float, default=0)
    memory_percent = Column(Float, default=0)
    network_rx_mb = Column(Float, default=0)
    network_tx_mb = Column(Float, default=0)
    recorded_at = Column(DateTime, default=datetime.utcnow)


class WebhookConfig(Base):
    __tablename__ = "webhook_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    secret = Column(String(255))
    events = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
