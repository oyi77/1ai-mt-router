# SAA Readiness Plan — 1ai-mt-router (Production-grade / SaaS-ready)

## Purpose

This file is the zero-context contract for swarm agents. Every coder agent dispatched to fix/implement work on this repo reads THIS file first, finds its bundle section, and executes ONLY that section. Agents do NOT run git commands. Every completion claim needs literal output (test/build receipts) per `_rules/VERIFICATION.md` — "receipt-or-not-done". If you cannot run tests, say `BLOCKED` explicitly with the reason rather than claiming done.

7-phase mapping:
- Phase 1 Explore (done — 26 agents, 63 CRIT/HIGH C1–C63, 38 MED M1–M38, LOWs)
- Phase 2 Understand/Plan (this file)
- Phase 3 Fix (Wave 0–1: infra/config/foundation bugs)
- Phase 4 Implement (Waves 2–5: feature/SaaS hardening)
- Phase 5 Review (review swarm, ~15 agents)
- Phase 6 QA (test/build/E2E swarm, ~10 agents, QA.md §9 evidence table)

## Verified findings (already confirmed by lead — do not re-litigate)

- C36 CONFIRMED: `statistics.py:66,150,191,238` call `mt5.get_deals_history(days=days)` but `MT5Service` defines `get_history_deals(symbol=None, days=30)` at `mt5_service.py:397` → all 4 `/stats` endpoints 500 (AttributeError). Fix = rename call sites to `get_history_deals(days=days)`.
- C18 CONFIRMED: `accounts.py:216` calls `mt5.check_server()`; only `_check_server()` exists (`mt5_service.py:60`). Fix = add public `check_server()` wrapper in mt5_service.py.
- C19 CONFIRMED: `MT5Account` model (`models/database.py:117–141`) has `encrypted_password` (line 130); `accounts.py:82` passes `password=encrypted_password` → TypeError on every create. Fix = `encrypted_password=encrypted_password`.
- C5 CONFIRMED: `main.py:152–161` SPA catch-all joins `full_path` into `FRONTEND_DIR` (absolute `frontend/dist`, defined `main.py:133–135`) with only `full_path.startswith("api/")` guard — no containment check; `..%2F` traversal can serve `.env`. Fix = realpath containment check.
- C7/C8 CONFIRMED: `backend/app/config.py:11` `JWT_SECRET="mt5-router-secret-key-change-in-production"`, `:24` `ENCRYPTION_KEY="your-fernet-key-here"`. NOTE: config lives at `backend/app/config.py` — there is NO `backend/app/core/config.py`. `core/` currently has only `database.py`, `__init__.py`.
- Stripe vars: `config.py:25–28` `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_BASIC_MONTHLY`, `STRIPE_PRICE_PRO_MONTHLY`; `:32` `NOWPAYMENTS_IPN_SECRET`. `.env.example` advertises `STRIPE_PRICE_ID_*` + `WEBHOOK_SECRET` (no Settings field) → B1 aligns naming.
- C9: `deployment/mt5-router.service:13` contains a real committed Fernet key → rotate first (B5's first action; generate new key, update file, document rotation).
- C45/C46: alembic has only `versions/001_initial_schema.py` + `env.py` (hardcoded SQLite); only 11/17 tables created; `create_all` used instead of migrations. C47: `middleware/rate_limit.py` exists but never registered; `services/redis_service.py` never imported.
- C10: `init_auth_enhancement_service()` never called in main.py lifespan (2FA/email/lockout dead code). C39/C44: alert_engine + webhook dispatch never started.
- C11/C12: `is_active` / role never checked against DB. C15/C16: passlib×bcrypt incompat → register 500; duplicate register endpoints.
- C30–C34: billing dead (Stripe webhooks log-only no-ops, placeholder price IDs, `trial_period_days` double-passed, NOWPayments IPN signature format wrong, `check_usage_limits` never called). C37: `notifications.py:85,123` `user.id` AttributeError. C41/C43: webhooks SSRF (arbitrary URL) + `/receive` no signature verification. C48/C49: prod DB_PASSWORD missing from env; hardcoded admin/admin123.
- C52–C57: frontend token stored as `"undefined"`, partial-close contract mismatch, MiniChart NaN crash, BillingPanel admin-gated, tier cents-vs-dollars, WS reconnect leak. C60: sync blocking calls in async endpoints (needs `asyncio.to_thread` + timeouts).
- MED highlights: M1 metrics key mismatch; M2 per-worker collector (decision: gate via ROLE env); M7 no instance resource limits; M9 no indexes; M12 tier JSON not mounted; M26 JWT in localStorage + no security headers; M27 missing error states; M32 docker.sock mount = root-equivalent (decision: keep for now, document risk + mitigation, do NOT remove without user ask — it's load-bearing for instance creation); M35 test env broken (aiosmtplib missing at conftest import + committed Fernet key at `conftest.py:4`); M36 `detail=str(e)` leaks; M37 SMTP header injection; M38 paramiko missing `allow_agent/look_for_keys=False`.

## Bundle sections

Each bundle: Files (exhaustive, disjoint across bundles) | Findings (C/M/LOW ids) | Instructions | Verification requirements.

### B1 Config & secrets
- Files: `backend/app/config.py`, `.env.example`, `backend/app/services/encryption.py`
- Findings: C7, C8, C48, M36-adjacent; Stripe env naming alignment.
- Instructions: Fail-fast Settings validation (pydantic): no insecure defaults — in prod env require JWT_SECRET, ENCRYPTION_KEY, DB_PASSWORD, SECRET_KEY etc. (raise on defaults or weak values); align `.env.example` names to actual Settings fields (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_BASIC_MONTHLY`, `STRIPE_PRICE_PRO_MONTHLY`, `NOWPAYMENTS_IPN_SECRET`, SMTP_* vars, `DATABASE_URL`); remove misleading `STRIPE_PRICE_ID_*`/`WEBHOOK_SECRET` entries; document all required envs in `.env.example` comments. Keep `encryption.py` API intact (B11/B15/B4 depend on Fernet helpers).
- Verification: `python -c "from app.config import Settings; print(Settings().model_dump().keys())"` lists correct fields; without env vars in prod-like settings raises.

### B2 App wiring
- Files: `backend/app/main.py`, `backend/app/middleware/rate_limit.py`, `backend/app/core/database.py`, `backend/app/services/redis_service.py`
- Findings: C5 (traversal), C6 (CORS `["*"]` + credentials → explicit origins from env, `allow_credentials=False` when `*`; keep Bearer auth), C10 (call `init_auth_enhancement_service()` in lifespan), C39/C44 (start alert engine + webhook dispatch tasks in lifespan with graceful shutdown), C47 (register rate-limit middleware; Redis-backed; X-Forwarded-For aware; fail-open with in-memory fallback if Redis down).
- Depends: B1 (config fields), B4 (storage), B11 (auth_enhancement wiring).
- Verification: app starts (`uvicorn app.main:app` imports clean); lifespan calls init; SPA catch-all rejects traversal (`curl --path-as-is /..%2F..%2F.env` → 403/404 not file); rate-limit header present on repeated requests.

### B3 Dep pinning
- Files: `backend/requirements.txt`, `frontend/package.json`, `frontend/package-lock.json`; CREATE `backend/requirements-dev.txt` (pytest, pytest-asyncio, httpx, aiosmtplib per M35).
- Findings: M35 (aiosmtplib missing), unpinned deps.
- Instructions: Pin exact versions in requirements.txt (compatible with Python 3.11+; keep current major versions, do NOT upgrade major frameworks blindly — verify import after). Add requirements-dev.txt with test deps pinned. Frontend: keep current dependency set; do NOT add runtime deps; only add devDeps needed by B7 (vitest, @testing-library/react, jsdom, msw) IF B7 not yet run — coordinate: if package.json already has them, skip.
- Verification: `pip install -r requirements.txt -r requirements-dev.txt` in a venv succeeds; backend imports clean; `npm install` succeeds with lockfile unchanged semantics.

### B4 Models & migration
- Files: `backend/app/models/database.py`, `backend/app/models/__init__.py`, `backend/alembic/env.py`, `backend/alembic/versions/002_*.py` (new), `backend/alembic/script.py.mako`, `backend/alembic.ini`
- Findings: C45 (only 11/17 tables — migration 002 adds missing: 2FA fields on users, api_keys, audit_logs, invoices, etc. — diff models vs 001 to enumerate), C46 (env.py hardcoded SQLite → read DATABASE_URL; make script async-safe if models use async SQLAlchemy), C17 (hash API keys/tokens at rest; encrypt 2FA seed + webhook secret with Fernet — decryptable per request for TOTP verify), M9 (indexes on FK columns and hot query columns).
- Instructions: Keep existing tables/columns stable (001 is deployed); write 002 additive-only migration; models must match migration; `alembic upgrade head` must work against a fresh SQLite + against a Postgres URL if available.
- Verification: `alembic upgrade head` on fresh DB creates all 17 tables; `alembic downgrade base` → `upgrade head` round-trips; `alembic check` reports no model/schema drift.

### B5 Infra & deploy
- Files: `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose*.yml` (all: compose.yml, dev, local, prod), `deployment/mt5-router.service`, `deployment/install-service.sh`, `cloudflared/config.yml`
- Findings: C9 (rotate Fernet key first — generate new key, update service file + .env.example, document rotation), C48 (prod DB_PASSWORD missing), C49 (hardcoded admin/admin123 → env-driven seed with strong defaults in prod), M32 (docker.sock mount — decision: keep, document risk + mitigation: only expose when INSTANCE_ORCHESTRATION=docker; recommend rootless/remote context; README operator note).
- Instructions: Align `.env.example` naming BEFORE B1 finishes (coordinate: read B1 diff if merged). Ensure compose files and service file reference same env names. Add resource limits to compose services (M7-adjacent). No new infra unless needed.
- Verification: `docker compose config` (each file) valid; `bash -n deployment/install-service.sh`; service file parses (systemd-analyze if available).

### B6 Backend tests
- Files: `backend/tests/**` (conftest.py ~77 lines, test_auth.py ~33, test_instances.py ~0)
- Findings: M35 (fixtures/env broken: aiosmtplib import at conftest, committed Fernet key at conftest.py:4 → move key to env/test fixture), empty test_instances.py.
- Instructions: Fix conftest (env fixture providing test JWT_SECRET/ENCRYPTION_KEY/DB URL; sqlite in-memory or tmp file; override Redis with dummy/fakeredis if used). Add tests: auth (register/login/2FA), trading endpoints, instances CRUD, billing checkout + webhook signature verification (unit with fake signature), webhook SSRF rejection, stats endpoints (C36 regression test), rate limit middleware.
- Runs AFTER implementation waves (Wave 5), but conftest/env fix can be earlier if needed.
- Verification: `pytest` green; at least the endpoints fixed by C-list have explicit regression tests.

### B7 Frontend test scaffold
- Files: CREATE `frontend/vitest.config.*`, `frontend/src/test/**` (setup), devDeps in package.json (vitest, @testing-library/react, jsdom, msw)
- Findings: no frontend tests at all.
- Instructions: Add minimal scaffold + a smoke test (renders App shell) and a token-persistence unit test (C52). Run AFTER B3 (package.json overlap). Do NOT add runtime deps.
- Verification: `npx vitest run` passes.

### B8 CI
- Files: `.github/workflows/ci.yml` (exists — rewrite/extend)
- Findings: CI inadequate or stale.
- Instructions: Jobs: backend (pytest), frontend (vitest + `npm run build` + `tsc --noEmit`), infra (`docker compose config`). Depends B3/B6/B7.
- Verification: workflow YAML valid (`actionlint` if available); jobs match repo scripts.

### B9 Logging & observability
- Files: CREATE `backend/app/core/logging.py`, CREATE `backend/app/core/audit.py`
- Findings: no structured logging; no audit trail.
- Instructions: JSON structured logging (stdlib logging + custom formatter; request-id middleware hook), `exc_info=True` helper, sanitize secrets in logs (redact password/token/key fields). `audit.py`: AuditLog writer helper (model from B4) — used by B11/B15/B16/B17.
- Verification: import clean; a logger call emits JSON with level/ts/msg; audit helper writes a row (when DB available).

### B10 Error-handling infra
- Files: CREATE `backend/app/core/exceptions.py`, CREATE `backend/app/core/http.py`
- Findings: M36 (`detail=str(e)` leaks), no central handlers, rollback hygiene, float serialization issues.
- Instructions: Central exception handlers (AppError → structured error JSON, no internals leaked), rollback-hygiene helper (rollback on error before raising), `inf`/`NaN`-safe JSON encoder for B16 stats (replace in app state if main.py has one, or export for use).
- Verification: import clean; raising AppError returns structured body; float('inf') serializes without crashing.

### B11 Auth & users
- Files: `backend/app/api/auth.py`, `backend/app/api/accounts.py`, `backend/app/auth/jwt.py`, `backend/app/auth/rbac.py`, `backend/app/auth/models.py`, `backend/app/api/users.py`, `backend/app/services/auth_enhancement_service.py`
- Findings: C10-runtime (init in B2 lifespan; make service actually functional — 2FA enable/verify, email send via SMTP, lockout tracking), C11 (check `is_active` on auth), C12 (check role via RBAC dependency), C13, C14, C15 (passlib×bcrypt incompat — use bcrypt directly or aligned passlib version), C16 (dedupe register endpoints — keep canonical, alias/remove duplicate), C17-runtime (hash API keys; encrypt 2FA seed), C19 (encrypted_password), M17–M19, M37 (SMTP header injection — validate sender/recipient, no CRLF), M35-regressions.
- Depends: B2 (lifespan), B4 (storage), B9 (audit), B10.
- Verification: register/login flows work; 2FA enable+verify round-trip; locked account after N failures; disabled account rejected; duplicate endpoint removed; regression tests for C15/C19.

### B12 Trading/MT5/copytrading
- Files: `backend/app/api/trading.py`, `backend/app/services/mt5_service.py`, `backend/app/api/copytrading.py`
- Findings: C1 (trading handlers missing/500), C4 (`/ticks` WS auth + symbol caps), C18 (add public `check_server()` wrapper), C20, C58, M4–M6, M36, C60 (to_thread+timeouts for all MT5 calls), LOW: response_model wiring, UTC timestamps, `days` cap, `delete_strategy` cascade, lot-multiplier validation, `update_strategy` body model.
- Decision (frozen): copy-trading gets CRUD + IDOR fixes ONLY. NO full replication engine — out of scope.
- Verification: trading endpoints return typed responses; WS ticks requires auth token; `check_server()` callable; sync MT5 calls off the event loop (to_thread); C36 regression (B16 stats) unaffected.

### B13 Instances & VNC
- Files: `backend/app/api/instances.py`, `backend/app/api/vnc.py`
- Findings: C1 (instance handlers), C2, C4 (VNC WS auth), C21, C22, M7 (resource limits — add to instance create payload validation + docker run), M10, M29 (first-stats zeroed precpu, instances.py:142-152), C60 (docker sync calls → to_thread), LOW: instance-name entropy, `image.tags` guard, VNC header whitelist, port-resolution via `Instance.vnc_port`.
- Verification: instance create/start/stop/delete work against Docker (or fail loudly if no docker daemon — state BLOCKED with receipt); WS auth enforced; resource limits present in payload validation.

### B14 Servers & SSH
- Files: `backend/app/api/servers.py`, `backend/app/services/ssh_service.py`
- Findings: C23–C29, M13, M14, M36, M38 (`allow_agent=False`, `look_for_keys=False`), C60 (paramiko off loop, hard timeouts), LOW: `shlex` hygiene, ed25519 key gen, IPv6 port regex, `df` column mapping (ssh_service.py:101-124), connection pooling (optional, note as follow-up).
- Verification: server test-connection works (or BLOCKED with receipt if no reachable SSH target); no agent key/auth leaks in code; timeouts present.

### B15 Billing/payments/admin
- Files: `backend/app/api/billing.py`, `backend/app/services/billing_service.py`, `backend/app/services/nowpayments_service.py`, `backend/app/api/admin.py`
- Findings: C30–C34, M15, M16, M12 (tier JSON mounted — admin API returns tier config from mounted file), C11 (billing checks is_active), M36, C56 backend boundary (cents↔dollars — API returns cents ints; document + enforce), LOW: Invoice writes, idempotent checkout, tier-override routing, `update_tier` bounds, `delete_user` soft-delete, AuditLog writes (B9).
- Verification: checkout creates pending payment; webhook handlers verify signature and flip subscription (unit test with fixtures — real Stripe/NOWPayments NOT available: mark NOT VERIFIED); tier config endpoint returns mounted JSON; no `detail=str(e)` leaks.

### B16 Monitoring/metrics/stats
- Files: `backend/app/api/monitoring.py`, `backend/app/services/metrics_collector.py`, `backend/app/api/statistics.py`
- Findings: C1 (stats IDOR — filter by owner), C3, C4 (`/stream` WS), C35, C36 (rename to `get_history_deals`), M1 (metrics key mismatch — align collector keys with consumer), M2 (ROLE gate for per-worker collector), M3, M8, M9, C60 (psutil/docker blocking → to_thread), LOW: `/alerts` stub → 501 or wire, UTC isoformat, eth0-vs-all nets, negative-CPU clamp, sleep jitter, `_collector_task` lock, retention cap 720h.
- Verification: stats endpoints return 200 with data (regression for C36); metrics keys consistent end-to-end; `float('inf')` safe (B10 encoder); WS stream authed.

### B17 Notifications/webhooks/alert
- Files: `backend/app/api/notifications.py`, `backend/app/api/webhooks.py`, `backend/app/services/notification_service.py`, `backend/app/services/alert_engine.py`
- Findings: C37 (`user.id` → use current user object/relation), C38, C39 (start engine in B2 lifespan), C40, C41 (SSRF — validate webhook target URL: block internal/loopback/link-local/169.254.169.254, allowlist schemes http/https; per QA.md App B), C42, C43 (`/receive` signature verification — verify NOWPayments IPN signature per their spec), C44 (dispatch task wiring), M21, M22, M36, LOW: channel Literal, HTML escaping, payload-log redaction.
- Verification: webhook create rejects `http://169.254.169.254` and `http://localhost`; `/receive` rejects bad signature (unit test); alert engine starts in lifespan; notification list 200.

### B18 Frontend API layer
- Files: `frontend/src/api/**` (client.ts, auth.ts, accounts.ts, servers.ts, admin.ts, billing.ts, instances.ts, monitoring.ts, notifications.ts, statistics.ts, trading.ts, webhooks.ts), `frontend/src/hooks/**` (useMetrics.ts, useWebSocket.ts), `frontend/src/context/AuthContext.tsx`
- Findings: C52 (token `"undefined"` — never persist empty string; storage helper checks truthiness), C53 (client side of partial-close contract), C57, M24, M25, M26 (localStorage kept — accepted; headers in B22), M27 (hook abort/in-flight state), LOW: ws→wss, contract typing (session_id, admin tier unwrap, invoice cents, expires_in).
- Verification: `tsc --noEmit` passes; token stored only when non-empty; unit test for token persistence (B7).

### B19 Frontend pages/app/dashboard/charts
- Files: `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/src/pages/**` (Dashboard, Landing, Login, Register), `frontend/src/components/dashboard/**` (InstanceCard, InstanceMetricsChart, MetricsCard, MetricsPanel), `frontend/src/components/charts/**` (MiniChart)
- Findings: C54, C55, M27, M29 (dashboard: `exited` restart, dead `stats` prop), LOW: error boundary, 404 route, redirect preservation, 423/2FA in Login, password-reset UI, Landing price guards, main.tsx refetchInterval.
- Verification: `npm run build` passes; MiniChart guards NaN (regression for C55); Dashboard renders with no console errors in dev.

### B20 Frontend trading/accounts
- Files: `frontend/src/components/trading/**` (PositionsTable, PriceChart, AccountCard), `frontend/src/components/accounts/**` (AccountsPanel)
- Findings: C53 (partial-close UI/contract — match backend response shape), M28, LOW: close-position confirm, SL/TP-clear sentinel, currency threading, PriceChart fix-or-delete (delete if unfixable — note it), precision formatting.
- Verification: `npm run build` passes; types align with backend contract (session_id etc.).

### B21 Frontend feature UI
- Files: `frontend/src/components/servers/**`, `vnc/**`, `webhooks/**`, `notifications/**`, `statistics/**`, `billing/**`, `admin/**`
- Findings: C56 (billing panel side — cents display), M30, LOW: VNCViewer spinner/error, StatisticsPanel equity chart + skeletons, SSRF-target UI validation, confirm dialogs, admin pagination, role-change confirm, revenue cents→dollars.
- Verification: `npm run build` passes; no hardcoded admin gates (C56).

### B22 Frontend UI kit & build
- Files: `frontend/src/components/ui/**` (11 files), `frontend/src/lib/utils.ts`, `frontend/tailwind.config.js`, `frontend/src/index.css`, `frontend/index.html`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/nginx.conf`, `frontend/postcss.config.js`
- Findings: M31, M26 (nginx security headers: CSP, X-Frame-Options, X-Content-Type-Options, HSTS, Referrer-Policy; body size limits; WS upgrade-only proxy), LOW: dialog a11y/Escape, AlertDialog async close, tabs ARIA, tsconfig strict, formatBytes/formatUptime/formatCurrency guards, button `type`.
- Verification: `npm run build` passes; `nginx -t` on nginx.conf (if nginx installed; else note BLOCKED); headers present in nginx.conf.

## Wave sequence (enforce strictly — avoids file conflicts)

- Wave 0a parallel: B3, B9, B10
- Wave 0b: B7 (after B3 — package.json overlap)
- Wave 1 parallel: B1, B4, B5 (B5's `.env.example` naming lands before B1 finishes; B5 first action = rotate C9 Fernet key)
- Wave 2: B2 (after B1/B4) → B11 (after B2 lifespan)
- Wave 3 parallel (max 6): B12, B13, B14, B15, B16, B17 (each depends only on B2/B4/B10)
- Wave 4: B18 first, then parallel B19, B20, B21, B22 (contracts frozen by Wave 3)
- Wave 5: B6, B7-test-writing, B8, B5 final docs rewrite (README/AGENTS.md/CODEBASE.md — last, must follow verified behavior; update AGENTS.md repo-specific conventions + Commands sections to reflect reality)

## Decisions log

1. Copy-trading: CRUD + IDOR fixes only; NO replication engine.
2. Metrics per-worker collector: gate via ROLE env (worker role enables it).
3. docker.sock: keep mount (load-bearing for instance creation), document risk + mitigation in README (rootless/remote context recommendation).
4. JWT in localStorage: accepted for now; mitigated by nginx security headers (B22) + short expiry; documented as follow-up.
5. Deployment topology: systemd host path (backend :8080 + static mount) + cloudflared stays; compose stack for container deploys; env naming aligned.
6. Price IDs are env-driven; no hardcoded Stripe prices.
7. `/alerts` stub: wire it to alert_engine data or return 501 (not a silent empty 200).

## VERIFY resolution table

| Finding | Status | Resolution |
|---|---|---|
| C36 | CONFIRMED | rename to `get_history_deals(days=days)` (B16) |
| C18 | CONFIRMED | add public `check_server()` in mt5_service.py (B12) |
| C19 | CONFIRMED | `encrypted_password=encrypted_password` (B11) |
| C5 | CONFIRMED | realpath containment in SPA catch-all (B2) |
| C7/C8 | CONFIRMED | fail-fast config + env-driven secrets (B1) |
| C9 | CONFIRMED | rotate Fernet key first (B5) |
| C10 | CONFIRMED | call init in lifespan (B2) + functional service (B11) |
| C15/C16 | CONFIRMED | bcrypt direct; dedupe register (B11) |
| C47 | CONFIRMED | register rate-limit middleware (B2) |
| M35 | CONFIRMED | aiosmtplib in dev reqs; conftest env fixture (B3/B6) |
| C30–C34 | CONFIRMED | billing rework (B15) |
| C41/C43 | CONFIRMED | SSRF + signature verification (B17) |
| C52–C57 | CONFIRMED | frontend fixes (B18–B21) |

## Hard rules for every agent

1. NO git mutations (no add/commit/push/reset/rebase).
2. Minimal changes; no speculative refactors; match surrounding code style.
3. No new dependencies unless explicitly listed (B3/B7 add test deps only).
4. Read the target file first; if a finding is already fixed, note it and move on.
5. Completion requires literal receipts per `_rules/VERIFICATION.md` (banned: "it should work", bare "done"). If you cannot run the verification, say `BLOCKED: <reason>`.
6. Keep scope to your bundle's files. Cross-bundle changes: only via the shared contracts above (models from B4, exceptions from B10, audit from B9, config from B1).
7. QA phase follows `_rules/QA.md` §9 evidence-table style.
