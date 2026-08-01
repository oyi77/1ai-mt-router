# CODEBASE.md — MT5 Router (SaaS Trading Platform)

> Codebase map for AI agents. Last verified: 2026-08-01 (files listed are confirmed on disk).

## Purpose

Multi-tenant SaaS for operating MetaTrader 5 trade routers: Docker-based MT5
instances with browser-based noVNC access, a REST + WebSocket trading API, copy
trading, billing (Stripe + NOWPayments), notifications (Telegram / webhooks),
statistics, and multi-server SSH management.

## Tech Stack (versions from `backend/requirements.txt`, `frontend/package.json`)

- **Backend:** Python 3.11+, FastAPI 0.141, SQLAlchemy 2.0, Alembic 1.18, Uvicorn 0.52 / Gunicorn 26
- **Frontend:** React 18, TypeScript 5, Vite 5, Tailwind 3, TanStack Query 5, Vitest 2
- **MT5:** mt5linux 1.0.11, Docker (`lprett/mt5linux:mt5-installed`)
- **Auth:** PyJWT 2.13, pyotp 2.10 (2FA/TOTP), passlib/bcrypt 1.7, API keys (prefix `mtr_`)
- **Infra:** Docker Compose, Cloudflare Tunnel (`cloudflared/`), Redis, PostgreSQL 15 (prod overlay)
- **SSH:** paramiko 5.0 (multi-server management)
- **Payments:** stripe 15.4, NOWPayments (crypto)
- **Notifications:** Telegram Bot API, webhooks, SMTP (aiosmtplib)
- **Monitoring:** psutil, WebSocket streaming

## Entry Points

| Entry | Command | Description |
|-------|---------|-------------|
| `backend/app/main.py` | `uvicorn app.main:app` | FastAPI app (lifespan, 14 routers, static frontend) |
| `backend/gunicorn.conf.py` | `gunicorn -c gunicorn.conf.py app.main:app` | Production server |
| `frontend/` | `cd frontend && npm run dev` | React dashboard (Vite) |
| `docker-compose.yml` | `docker-compose up -d` | Base stack (backend + frontend, SQLite) |
| `docker-compose.prod.yml` | `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d` | Adds postgres:15 + redis:7, Postgres URL (`DB_PASSWORD` required) |
| `docker-compose.dev.yml` / `.local.yml` | `-f docker-compose.yml -f docker-compose.dev.yml up -d` | Dev overlays (uvicorn `--reload`, src mounts) |
| `setup.sh` / `start.sh` | `./setup.sh` / `./start.sh` | Setup and start scripts |

## Directory Structure (verified)

```
1ai-mt-router/
├── backend/                     # FastAPI backend
│   ├── app/
│   │   ├── main.py              # App factory, lifespan, router mounts, static frontend
│   │   ├── config.py            # pydantic-settings Settings (env-based)
│   │   ├── api/                 # 14 routers, mounted under /api/v1/*
│   │   │   ├── auth.py users.py admin.py
│   │   │   ├── instances.py vnc.py monitoring.py
│   │   │   ├── trading.py accounts.py copytrading.py statistics.py
│   │   │   ├── notifications.py webhooks.py
│   │   │   ├── servers.py billing.py
│   │   │   └── __init__.py
│   │   ├── auth/                # jwt.py, models.py, rbac.py
│   │   ├── core/                # database.py (engine), audit.py, exceptions.py, http.py, logging.py
│   │   ├── middleware/          # rate_limit.py (RateLimitMiddleware)
│   │   ├── models/              # database.py — all SQLAlchemy models + Base
│   │   └── services/            # mt5_service, ssh_service, billing_service,
│   │                            # nowpayments_service, auth_enhancement_service,
│   │                            # alert_engine, notification_service, metrics_collector,
│   │                            # redis_service, encryption
│   ├── alembic/                 # env.py + versions/ (001_initial_schema, 002_add_missing_tables_and_indexes)
│   ├── tests/                   # conftest.py, test_auth.py, test_instances.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── gunicorn.conf.py
├── frontend/                    # React dashboard
│   ├── src/
│   │   ├── main.tsx App.tsx index.css
│   │   ├── api/                 # client.ts + one module per router (auth, trading, instances, ...)
│   │   ├── components/          # accounts, admin, billing, charts, dashboard, notifications,
│   │   │                        # servers, statistics, trading, ui, vnc, webhooks
│   │   ├── pages/               # Landing, Login, Register, Dashboard
│   │   ├── context/             # AuthContext.tsx
│   │   ├── hooks/               # useWebSocket.ts, useMetrics.ts
│   │   ├── lib/                 # utils.ts
│   │   └── test/                # App.test.tsx, token-persistence.test.tsx, setup.ts (Vitest + MSW)
│   ├── package.json             # scripts: dev, build, preview, test
│   ├── Dockerfile (nginx)       # serves built app on :80
│   └── nginx.conf
├── cloudflared/                 # config.yml (Cloudflare Tunnel)
├── deployment/                  # install-service.sh, mt5-router.service (systemd)
├── .github/workflows/ci.yml     # backend pytest + flake8 on push/PR to master
├── docker-compose.yml / .dev.yml / .local.yml / .prod.yml
├── setup.sh / start.sh
└── .env.example                 # every config variable, documented
```

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app — lifespan (DB create, service init, alert engine, metrics), 14 router mounts under `/api/v1`, health endpoints, serves `frontend/dist` when built |
| `backend/app/config.py` | `Settings` (pydantic-settings) — the single source of env configuration |
| `backend/app/models/database.py` | All SQLAlchemy models + `Base` |
| `backend/app/core/database.py` | SQLAlchemy engine / session setup |
| `backend/app/services/mt5_service.py` | MT5 Docker instance lifecycle + VNC |
| `backend/app/services/ssh_service.py` | Multi-server SSH via paramiko (encrypted credentials) |
| `backend/app/services/billing_service.py` | Stripe checkout, portal, webhooks |
| `backend/app/services/nowpayments_service.py` | NOWPayments crypto payments |
| `backend/app/auth/rbac.py` | Role-based access control |
| `frontend/src/api/client.ts` | Shared fetch client used by all frontend API modules |
| `cloudflared/config.yml` | Cloudflare Tunnel routing |

## Architecture

```
React Dashboard (Vite/TS) ──REST/WS──▶ FastAPI Backend
                                           │
                     ┌─────────────────────┼─────────────────────┐
               Auth (JWT+2FA)        Trading API            Instance Mgmt
               API keys / RBAC       Copy trading           Docker MT5 + VNC
               Billing               Statistics             Multi-SSH servers
               Notifications / alerts
                                           │
                     SQLite (dev) / PostgreSQL 15 + Redis 7 (prod overlay)
```

The backend manages MT5 instance containers through the Docker socket (or a
remote context when `INSTANCE_ORCHESTRATION=remote`). Secrets at rest (2FA seeds,
webhook targets, SSH keys) are encrypted with a Fernet key (`ENCRYPTION_KEY`).
The alert engine and notification dispatch run as in-process asyncio loops started
in the app lifespan.

## Run Commands

```bash
# Setup
cp .env.example .env  # edit with your settings

# Base stack (backend + frontend, SQLite)
docker-compose up -d

# Dev with hot reload
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Production (PostgreSQL + Redis; DB_PASSWORD required in .env)
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Backend: http://localhost:8080  (API docs: /api/docs, health: /api/health)
# Frontend: http://localhost:3000

# Tests
cd backend && python -m pytest tests/ -q
cd frontend && npm run test
```

## Environment Variables

Every variable is documented in `.env.example`; all map 1:1 to
`backend/app/config.py::Settings`. Highlights:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `development` | `development` \| `test` \| `production` (production enables fail-fast secret validation) |
| `JWT_SECRET` | — | JWT signing secret (≥ 32 chars, required in production) |
| `ENCRYPTION_KEY` | — | Fernet key for secrets at rest (2FA seeds, webhook targets, SSH keys) |
| `DATABASE_URL` | `sqlite:///./data/mt5router.db` | SQLite (dev) or PostgreSQL (prod) |
| `DB_PASSWORD` | — | Required when `DATABASE_URL` is `postgres://` |
| `INSTANCE_ORCHESTRATION` | `docker` | `docker` (local socket) or `remote` (rootless/remote context) |
| `MT5_IMAGE` | `lprett/mt5linux:mt5-installed` | Docker image for MT5 instances |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | — | Enables Stripe billing when set |
| `NOWPAYMENTS_API_KEY` / `NOWPAYMENTS_IPN_SECRET` | — | Enables NOWPayments when set |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` / `FROM_EMAIL` | — | Email verification / password reset |
| `RATE_LIMIT_PER_MINUTE` | `100` | API rate limit |
| `CORS_ORIGINS` | `*` | CORS origins (comma-separated) |
