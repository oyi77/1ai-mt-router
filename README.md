# MT5 Router — SaaS Trading Platform

Multi-tenant SaaS for operating MetaTrader 5 trade routers: manage MT5 instances
(Docker containers with VNC access), trade through a REST + WebSocket API, copy
trades between accounts, subscribe to subscriptions, and get alerts via Telegram
or webhooks.

## Architecture

```
React + Vite (frontend)  ──REST/WS──▶  FastAPI (backend)
                                          │
                    ┌─────────────────────┼─────────────────────┐
              Auth (JWT + API keys)  Trading API           Instance Mgmt
              Users / admin          Copy trading          Docker + VNC
              Billing                Statistics            Multi-server SSH
              Notifications / alerts
                                          │
                     SQLite (dev) / PostgreSQL + Redis (prod)
```

- **Frontend** — React 18 + TypeScript + Vite 5 + Tailwind 3. Served on port
  `3000` (nginx in Docker). The backend also serves the built frontend from
  `frontend/dist` when present.
- **Backend** — Python 3.11 + FastAPI + SQLAlchemy 2 + Alembic. REST + WebSocket
  API on port `8080`, interactive docs at `/api/docs`, health check at `/api/health`.
- **MT5 instances** — Docker containers based on `lprett/mt5linux:mt5-installed`,
  managed by the backend through the Docker socket (or a remote Docker context),
  with browser-based noVNC access.
- **Database** — SQLite by default (dev); PostgreSQL 15 + Redis 7 are added by the
  production compose overlay.

## Services (compose)

| Service  | Port          | Notes                                              |
|----------|---------------|----------------------------------------------------|
| backend  | 8080 → 8080   | FastAPI; mounts `/var/run/docker.sock`, `./data`, `./logs` |
| frontend | 3000 → 80     | nginx-served React build                            |
| postgres | (internal)    | `docker-compose.prod.yml` only, `postgres:15-alpine` |
| redis    | (internal)    | `docker-compose.prod.yml` only, `redis:7-alpine`     |

## Quick Start

```bash
cp .env.example .env   # edit with your settings (see .env.example for every option)
```

Base stack (backend + frontend, SQLite):
```bash
docker-compose up -d
```

Development with hot reload (uvicorn `--reload`, `backend/app` and `frontend/src`
mounted):
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Local development variant (same as dev, also mounts `frontend/public`):
```bash
docker-compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

Production (PostgreSQL + Redis; `DB_PASSWORD` is required in `.env`):
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

After starting, open http://localhost:3000 (frontend) and http://localhost:8080/api/docs
(API docs).

### Admin account

No default credentials are seeded. The initial admin account is created at startup
only when `ADMIN_PASSWORD` is set in `.env` (see `ADMIN_USERNAME`, `ADMIN_EMAIL`,
`ADMIN_PASSWORD` in `.env.example`). Set a strong password — never hardcode one.

### Docker Socket Access (⚠️ Security Note)

`docker-compose.yml` mounts the host Docker socket (`/var/run/docker.sock`) into
the backend container. This is load-bearing: the backend uses the socket to create
and manage MT5 instance containers while `INSTANCE_ORCHESTRATION=docker` (the
default in `.env.example`).

Because the socket grants the backend full control over the Docker daemon
(equivalent to root on the host), treat this deployment accordingly:

- Only expose this deployment on networks you trust while the socket is mounted —
  anyone who can reach the backend can reach the Docker daemon.
- For multi-tenant / hosted deployments prefer rootless Docker or a remote Docker
  context and set `INSTANCE_ORCHESTRATION=remote` (no socket mount).
- If instance orchestration is not used at all, remove the `/var/run/docker.sock`
  mount from `docker-compose.yml`.

## Configuration

All configuration is environment-based, defined in `backend/app/config.py`
(pydantic-settings `Settings`) and templated in `.env.example`. Key variables:

| Variable | Default / example | Description |
|----------|-------------------|-------------|
| `ENV` | `development` | `development` \| `test` \| `production` (production enables fail-fast secret validation) |
| `JWT_SECRET` | — | JWT signing secret (≥ 32 chars; required in production) |
| `ENCRYPTION_KEY` | — | Fernet key for secrets at rest (2FA seeds, webhook targets, SSH keys) |
| `DATABASE_URL` | `sqlite:///./data/mt5router.db` | SQLite (dev) or `postgresql://...` (prod) |
| `DB_PASSWORD` | — | Postgres password; required with `postgres://` URLs in production |
| `INSTANCE_ORCHESTRATION` | `docker` | `docker` (local socket) or `remote` (rootless/remote context) |
| `MT5_IMAGE` | `lprett/mt5linux:mt5-installed` | Docker image for MT5 instances |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | — | Enable Stripe billing when set |
| `NOWPAYMENTS_API_KEY` / `NOWPAYMENTS_IPN_SECRET` | — | Enable NOWPayments crypto payments when set |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` / `FROM_EMAIL` | — | Email verification / password reset |
| `TELEGRAM_*`, `WEBHOOK_*`, `REDIS_*`, `RATE_LIMIT_PER_MINUTE`, `CORS_ORIGINS` | — | Notifications, rate limiting, Redis, CORS |

## API Surface

All routes are under `/api/v1`, mounted in `backend/app/main.py`:

- `auth` — register, login, email verification, password reset, 2FA/TOTP
- `users` — user profile, API keys
- `instances`, `vnc` — MT5 Docker instance lifecycle and VNC access
- `trading` — orders, positions, candles, ticks (WebSocket)
- `monitoring` — system metrics (WebSocket stream)
- `accounts` — MT5 broker account connections (credentials encrypted at rest)
- `copy` — copy-trading strategies and subscribers
- `stats` — trading statistics, equity curves, symbol breakdown
- `notifications`, `webhooks` — Telegram, alert rules, TradingView/custom webhooks
- `servers` — multi-server SSH management
- `billing` — Stripe subscriptions, invoices, usage; NOWPayments crypto payments
- `admin` — admin management

## Testing & Build

Backend (pytest):
```bash
cd backend && python -m pytest tests/ -q
```

Frontend (vitest):
```bash
cd frontend && npm run test
```

Frontend build:
```bash
cd frontend && npm run build
```

CI (`.github/workflows/ci.yml`) runs the backend tests and a flake8 lint
(`flake8 app/ --select=E9,F63,F7,F82`) on push/PR to `master`.
