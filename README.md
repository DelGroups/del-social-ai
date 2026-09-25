# DEL SOCIAL AI

AI-assisted social media platform for DEL Groups.

| Host | Serves |
|---|---|
| https://app.del-groups.com | Next.js panel |
| https://api.del-groups.com | FastAPI (API, webhooks, media) |
| https://ai.del-groups.com | Redirects to the panel |

## Status: Phase 0 (skeleton)

Infrastructure only. The app directories are empty placeholders.

```
apps/
  api/        FastAPI backend       (empty)
  web/        Next.js panel         (empty)
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
- `api` and `web` sit behind the `app` Compose profile until they have Dockerfiles.

## Prerequisites

- Docker Engine 24+ with the Compose v2 plugin
- Production: DNS **A records** for `app`, `api` and `ai.del-groups.com` pointing to the server, with ports **80 and 443** open

## Setup

```bash
# 1. Configure the environment
cp .env.example .env
# Replace every CHANGE_ME (generate values with: openssl rand -hex 32).
# DATABASE_URL and REDIS_URL must use the same passwords.

# 2. Start the infrastructure
docker compose up -d

# 3. Verify
docker compose ps                        # postgres and redis should be "healthy"
curl https://api.del-groups.com/healthz  # -> ok   (local: curl -k https://api.localhost/healthz)
```

### Local development

In `.env`, set `APP_DOMAIN=app.localhost`, `API_DOMAIN=api.localhost` and `AI_DOMAIN=ai.localhost`. Caddy then uses its own local CA, and no public DNS is needed.
Until the apps exist, every route except `/healthz` returns 502. This is expected.

### Once the apps exist (Phase 1+)

Add `apps/api/Dockerfile` (listening on port 8000) and `apps/web/Dockerfile` (listening on port 3000). Then run:

```bash
docker compose --profile app up -d --build
```

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
