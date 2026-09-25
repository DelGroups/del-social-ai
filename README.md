# DEL SOCIAL AI

AI-assisted social media platform for DEL Groups.

| Host | Serves |
|---|---|
| https://app.del-groups.com | Next.js panel |
| https://api.del-groups.com | FastAPI (API, webhooks, media) |
| https://ai.del-groups.com | Redirects to the panel |

## Status: Phase 0 (skeleton)

Infrastructure plus minimal app shells: the API exposes `/health` and `/ready`, and the panel shows a system-status page.

```
apps/
  api/        FastAPI backend       (health/readiness only)
  web/        Next.js panel         (status page only)
infra/
  Caddyfile   TLS + reverse proxy
docs/         Project docs
evals/        LLM eval cases        (empty)
docker-compose.yml
.env.example
```

## Architecture

```
internet ──► Caddy :80/:443 ──┬─ api.del-groups.com ──► api:8000 (FastAPI) ──┬─► Postgres 16
                              ├─ app.del-groups.com ──► web:3000 (Next.js)  └─► Redis 7
                              └─ ai.del-groups.com  ──► 301 → app
```

- Caddy provisions and renews Let's Encrypt certificates on its own. HTTP is redirected to HTTPS.
- Postgres and Redis are published on `127.0.0.1` only, so they are never reachable from outside the host.
- `api` and `web` are built from `apps/*/Dockerfile` and run as non-root users.

## Prerequisites

- Docker Engine 24+ with the Compose v2 plugin
- Production: DNS **A records** for `app`, `api` and `ai.del-groups.com` pointing to the server, with ports **80 and 443** open

## Setup

```bash
# 1. Configure the environment
cp .env.example .env
# Replace every CHANGE_ME (generate values with: openssl rand -hex 32).
# DATABASE_URL and REDIS_URL must use the same passwords.

# 2. Build and start everything
docker compose up -d --build

# 3. Verify
docker compose ps                        # all 5 services should be "healthy" / "running"
curl https://api.del-groups.com/ready    # -> {"status":"ok",...}  (local: curl -k https://api.localhost/ready)
# open https://app.del-groups.com         # status page, every row ✅
```

### Local development

In `.env`, set `APP_DOMAIN=app.localhost`, `API_DOMAIN=api.localhost` and `AI_DOMAIN=ai.localhost`. Caddy then uses its own local CA, and no public DNS is needed.

## Database & tests

Tenant isolation uses Postgres Row-Level Security; see [ADR 001](docs/decisions/001-multi-tenant-rls.md).

```bash
cd apps/api
pip install -e ".[dev]"

# Tests need a throwaway DB whose name contains "test" (superuser URL)
export TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/del_social_test
pytest -v

# Migrations run as the DB owner
export MIGRATION_DATABASE_URL=...
alembic upgrade head
```

CI (`.github/workflows/test.yml`) runs the full suite against a fresh Postgres 16 on every push to `main` and on every PR.

## Operations

| Task | Command |
|---|---|
| Logs | `docker compose logs -f caddy` |
| psql shell | `docker compose exec postgres psql -U $POSTGRES_USER $POSTGRES_DB` |
| Backup DB | `docker compose exec -T postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql` |
| Reload Caddyfile | `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile` |
| Stop | `docker compose down` (add `-v` to **delete all data**) |

## Security notes

- `.env` is gitignored. Never commit real keys.
- Rotate `ANTHROPIC_API_KEY` if it ever appears in logs or git history.
- The `caddy_data` volume holds the TLS certificates. Keep it, so the server doesn't hit Let's Encrypt rate limits after a restart.
