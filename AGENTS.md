<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 | Updated: 2026-05-17 -->

# mt5-router

## Purpose
MetaTrader 5 management dashboard with VNC access, trading API, and real-time monitoring. Simplifies management of multiple MT5 instances across brokers.

## Key Files
| File | Description |
|------|-------------|
| `docker-compose.yml` | Container orchestration |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `backend/` | Node.js API server |
| `frontend/` | React dashboard UI |
| `cloudflared/` | Cloudflare Tunnel configuration |
| `deployment/` | Deployment scripts and configs |
| `nginx/` | Nginx reverse proxy config |

## For AI Agents

### Working In This Directory
- Independent project with microservices architecture
- cd into this directory before running commands
- Uses Docker for deployment

### Testing Requirements
- Verify backend API endpoints

## Dependencies

### Internal
None — standalone repo

### External
- Node.js — Backend runtime
- React — Frontend dashboard
- Docker — Container deployment
- MetaTrader 5 Manager API
