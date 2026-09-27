import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from del_social import __version__
from del_social.core.config import get_settings
from del_social.billing.quota import QuotaError
from del_social.routes import (
    auth,
    brand,
    connections,
    daily,
    evals,
    media,
    plan,
    platform,
    posts,
    products,
    strategy,
    team,
    tenants,
    usage,
)

settings = get_settings()

# httpx logs request URLs at INFO; Telegram bot tokens are part of the URL (ADR 003)
logging.getLogger("httpx").setLevel(logging.WARNING)

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Background loops: publishing approved posts at their time (team.scheduler) and the team's
    own morning work, market research and the Team Lead's report (team.daily)."""
    from del_social.core import deps
    from del_social.llm import build_llm
    from del_social.team import daily, lead, scheduler

    tasks = []
    http = deps._http()
    meta, vault = deps.get_meta_optional(http), deps._vault()
    if settings.scheduler_enabled and meta is not None and vault is not None:
        tasks.append(asyncio.create_task(scheduler.loop(engine=deps._engine(), settings=settings, meta=meta, vault=vault)))
    if settings.scheduler_enabled and settings.anthropic_api_key:
        llm = build_llm(settings, deps._engine(), http)
        tasks.append(asyncio.create_task(daily.loop(engine=deps._engine(), http=http, llm=llm, meta=meta, vault=vault)))
    yield
    for task in tasks:
        task.cancel()
    await lead.settle()


app = FastAPI(
    lifespan=lifespan,
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



@app.exception_handler(QuotaError)
async def quota_exceeded(_, exc: QuotaError) -> JSONResponse:
    """The package does not allow this: the panel shows the message and a link to upgrade."""
    return JSONResponse(status_code=402, content={"detail": str(exc), "code": exc.code})


app.include_router(auth.router)
app.include_router(plan.router)
app.include_router(daily.router)
app.include_router(strategy.router)
app.include_router(tenants.router)
app.include_router(platform.router)
app.include_router(connections.router)
app.include_router(brand.router)
app.include_router(usage.router)
app.include_router(evals.router)
app.include_router(media.router)
app.include_router(products.router)
app.include_router(posts.router)
app.include_router(team.router)
app.include_router(media.public_router)
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
