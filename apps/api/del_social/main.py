import asyncio
import logging

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from del_social import __version__
from del_social.core.config import get_settings
from del_social.routes import auth, connections, platform, tenants

settings = get_settings()

# httpx logs request URLs at INFO; Telegram bot tokens are part of the URL (ADR 003)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(
    title="DEL SOCIAL AI",
    version=__version__,
    # No public API docs in production
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(platform.router)
app.include_router(connections.router)
app.include_router(connections.callback_router)


@app.get("/")
async def root() -> dict:
    return {"name": "DEL SOCIAL AI", "version": __version__}


@app.get("/health")
async def health() -> dict:
    """Liveness: the process is up. Does not touch dependencies."""
    return {"status": "ok"}


async def _check_postgres() -> None:
    conn = await asyncpg.connect(settings.asyncpg_dsn, timeout=3)
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()


async def _check_redis() -> None:
    client = Redis.from_url(settings.redis_url, socket_timeout=3)
    try:
        await client.ping()
    finally:
        await client.aclose()


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness: Postgres and Redis are reachable. Errors are not echoed (may contain DSNs)."""
    results = await asyncio.gather(_check_postgres(), _check_redis(), return_exceptions=True)
    checks = {
        name: "ok" if not isinstance(r, BaseException) else "error"
        for name, r in zip(("postgres", "redis"), results)
    }
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
