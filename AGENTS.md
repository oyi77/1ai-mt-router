# AGENTS.md — 1ai-mt-router

## MANDATORY PROCESS (8 Steps — No Skipping)

Every task follows this sequence. No exceptions.

1. **AUDIT** — Read existing code. Understand current state.
2. **THINK** — Understand WHY. Intent vs literal.
3. **BRAINSTORM** — ≥3 approaches. Score options.
4. **PLAN** — Decompose. Risks. Rollback plan.
5. **EXECUTE** — Build. TDD when possible.
6. **TEST** — Run all tests. Break it first.
7. **VERIFY** — Prove with literal output.
8. **REVIEW** — Read your own diff before committing.

Full details: `~/.1ai/core/PROCESS.md` (auto-injected by hooks)

## This repo
MT5 Router — a multi-tenant SaaS for operating MetaTrader 5 trade routers: MT5 instance
lifecycle (Docker + VNC), trading API, copy trading, billing, notifications, and statistics.
Stack: Python 3.11 + FastAPI 0.141 + SQLAlchemy 2 + Alembic (backend); React 18 + TypeScript + Vite 5 + Tailwind 3 (frontend); Docker Compose deployment
Domain: MT5 trade router / trade-copying SaaS — instances, copytrading, billing, stats, notifications

## Rules — thin loader, no submodule
Rules are NOT vendored into this repo. This repo does NOT need a rules submodule.
`AGENTS.md` is only the repo-local loader: domain, commands, conventions, and pointers to `~/.1ai`.

Engineering rules are enforced by machine-level loaders when `setup-dev.sh` has been run:
- Claude Code: SessionStart hook injects `~/.1ai/core/RULES.md`
- OpenCode: plugin injects `~/.1ai/core/RULES.md`
- OMP: wrapper appends `~/.1ai/core/RULES.md` to launch sessions

Primary rules file:
```bash
cat ~/.1ai/core/RULES.md
```

Pre-ship gate:
```bash
cat ~/.1ai/core/GATE.md
```

If `~/.1ai` or auto-load is missing, run:
```bash
bash ~/.1ai/scripts/setup-dev.sh
```

Do NOT add the rules repo as a git submodule. Update rules centrally, then run/sync the thin `AGENTS.md` template.

## Hard rules
1. Read code before writing code.
2. No completion claim without literal receipt.
3. Compile/test/use like a real user before claiming work is ready.
4. Task must match this repo domain.
5. Run GATE.md before commit/PR.

## Repo-specific conventions
- One router module per domain in `backend/app/api/` (auth, trading, instances, billing, ...), all mounted in `backend/app/main.py` under `/api/v1/*`
- SQLAlchemy models + Base live in `backend/app/models/database.py`; engine/session in `backend/app/core/database.py`; business logic in `backend/app/services/`
- Frontend API layer in `frontend/src/api/` (one module per backend router), shared fetch client in `frontend/src/api/client.ts`
- Env config via pydantic-settings `Settings` in `backend/app/config.py`; template in `.env.example`

## Commands
- Dev (frontend): `cd frontend && npm run dev` (Vite)
- Test (frontend): `cd frontend && npm run test` (vitest)
- Build (frontend): `cd frontend && npm run build` (tsc && vite build)
- Test (backend): `cd backend && /tmp/b3verify/bin/python -B -m pytest tests/ -q`
- Lint (backend, CI): `cd backend && flake8 app/ --select=E9,F63,F7,F82`
