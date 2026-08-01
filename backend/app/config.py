from typing import List

from cryptography.fernet import Fernet
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Values that are never acceptable for secrets in production, regardless of
# whether they come from defaults, .env, or compose `${VAR:-...}` fallbacks.
_WEAK_SECRET_VALUES = {
    "changeme",
    "change-me",
    "change_me",
    "changethis",
    "changethis-to-a-secure-random-string-64-chars-min",
    "change-this-to-a-secure-random-string-64-chars-min",
    "secret",
    "password",
    "placeholder",
    "your-fernet-key-here",
    "mt5-router-secret-key-change-in-production",
}


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "MT5 Router"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    # Runtime environment: "development" | "test" | "production".
    # Fail-fast secret validation below only applies when ENV=production, so
    # `import app.main` keeps working in dev/test with the sensible defaults.
    ENV: str = "development"

    # --- Security ---
    # Required in production: random string >= 32 chars. The bundled default is
    # a dev-only placeholder and is rejected when ENV=production.
    JWT_SECRET: str = "mt5-router-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    # General-purpose server secret (used by future admin/session features).
    # Required in production; empty in dev.
    SECRET_KEY: str = ""
    # Fernet key for encrypting secrets at rest (2FA seeds, webhook targets,
    # SSH keys). Required in production. Empty in dev -> encryption service
    # falls back to an ephemeral per-process key (data not stable across
    # restarts; fine for local dev).
    ENCRYPTION_KEY: str = ""

    # --- CORS ---
    # Comma-separated origin list. Use "*" only for development.
    # Exposed as `settings.cors_origins` (list[str]) for app wiring.
    CORS_ORIGINS: str = "*"

    # --- Database ---
    DATABASE_URL: str = "sqlite:///./data/mt5router.db"
    # PostgreSQL password, required in production when DATABASE_URL is a
    # postgres:// URL (C48). Unused for SQLite.
    DB_PASSWORD: str = ""
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # --- Docker / instance orchestration ---
    DOCKER_SOCKET: str = "unix:///var/run/docker.sock"
    MT5_IMAGE: str = "lprett/mt5linux:mt5-installed"
    MT5_NETWORK: str = "bridge"
    MT5_RPYC_PORT: int = 18812
    MT5_VNC_PORT: int = 6081
    # "docker" (local socket) or "remote" (rootless/remote docker context).
    # The docker.sock mount should only be exposed when this is "docker".
    INSTANCE_ORCHESTRATION: str = "docker"

    # --- Metrics / alerts ---
    METRICS_INTERVAL: int = 10
    ALERT_COOLDOWN: int = 300

    # --- Rate limiting / API keys ---
    API_KEY_PREFIX: str = "mtr_"
    RATE_LIMIT_PER_MINUTE: int = 100
    # Comma-separated proxy addresses allowed to set the client IP via the
    # X-Forwarded-For header. Empty -> the header is ignored and the socket
    # peer address is used (prevents IP spoofing). "*" trusts any proxy
    # (tests / single-hop deployments).
    TRUSTED_PROXIES: str = ""

    # --- Stripe (optional; empty disables billing init) ---
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_BASIC_MONTHLY: str = ""
    STRIPE_PRICE_PRO_MONTHLY: str = ""
    STRIPE_PRICE_BASIC_YEARLY: str = ""
    STRIPE_PRICE_PRO_YEARLY: str = ""

    # --- NOWPayments (crypto; optional) ---
    NOWPAYMENTS_API_KEY: str = ""
    NOWPAYMENTS_IPN_SECRET: str = ""
    NOWPAYMENTS_SANDBOX: bool = True

    # --- 1ai-payment aggregator (multi-gateway payments; optional) ---
    PAYMENT_BASE_URL: str = "http://localhost:3100"
    PAYMENT_API_KEY: str = ""
    PAYMENT_WEBHOOK_SECRET: str = ""
    PAYMENT_GATEWAY: str = "nowpayments"

    # --- Email (SMTP; optional) ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = ""
    BASE_URL: str = "https://mt-oc.aitradepulse.com"

    # --- Admin bootstrap ---
    # First-run admin account, created at startup only when all three are
    # set. Leaving them empty skips admin creation entirely (no-op at boot).
    ADMIN_USERNAME: str = ""
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    # --- Redis ---
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("ENV")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        allowed = {"development", "test", "production"}
        if v.lower() not in allowed:
            raise ValueError(
                f"ENV must be one of {sorted(allowed)}, got {v!r}"
            )
        return v.lower()

    @model_validator(mode="after")
    def _fail_fast_in_production(self) -> "Settings":
        """Reject insecure/missing settings when ENV=production.

        Development/test keep the bundled defaults so the app and test suite
        can import without any environment (see encryption.py temp-key path).
        """
        if self.ENV != "production":
            return self

        problems: List[str] = []

        def _weak(value: str) -> bool:
            return (not value) or value.lower() in _WEAK_SECRET_VALUES

        if _weak(self.JWT_SECRET) or len(self.JWT_SECRET) < 32:
            problems.append(
                "JWT_SECRET: required, >= 32 chars, random (not a placeholder)"
            )
        if _weak(self.SECRET_KEY) or len(self.SECRET_KEY) < 32:
            problems.append(
                "SECRET_KEY: required, >= 32 chars, random (not a placeholder)"
            )
        if _weak(self.ENCRYPTION_KEY):
            problems.append(
                "ENCRYPTION_KEY: required Fernet key (generate with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"`)"
            )
        else:
            try:
                Fernet(self.ENCRYPTION_KEY.encode())
            except Exception:
                problems.append(
                    "ENCRYPTION_KEY: must be a valid Fernet key "
                    "(32 url-safe base64-encoded bytes)"
                )

        if "postgres" in self.DATABASE_URL:
            if _weak(self.DB_PASSWORD):
                problems.append(
                    "DB_PASSWORD: required (and not a weak value) when "
                    "DATABASE_URL points at PostgreSQL"
                )

        if self.SMTP_HOST:
            missing = [
                name
                for name, value in (
                    ("SMTP_USER", self.SMTP_USER),
                    ("SMTP_PASSWORD", self.SMTP_PASSWORD),
                    ("FROM_EMAIL", self.FROM_EMAIL),
                )
                if not value
            ]
            if missing:
                problems.append(
                    "SMTP_HOST is set but missing: " + ", ".join(missing)
                )

        if problems:
            raise ValueError(
                "Refusing to start in production with insecure settings: "
                + "; ".join(problems)
            )
        return self

    @property
    def cors_origins(self) -> List[str]:
        """CORS_ORIGINS as a list (comma-separated in env; "*" passthrough)."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def trusted_proxies(self) -> List[str]:
        """TRUSTED_PROXIES as a list (comma-separated in env; "*" passthrough)."""
        return [proxy.strip() for proxy in self.TRUSTED_PROXIES.split(",") if proxy.strip()]


settings = Settings()
