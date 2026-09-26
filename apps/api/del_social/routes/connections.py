"""Connected channels of one tenant (ADR 003). Tokens go in, never come out.

Meta flow: start (state in Redis, bound to account + tenant) → Facebook dialog →
callback (code → long-lived user token → pages, kept encrypted in Redis for 15 min)
→ the person picks a page in the panel → Facebook page + its Instagram account saved.
"""
import json
import logging
import secrets
import uuid
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.connections import CHANNELS, build_adapters
from del_social.connections.base import ChannelAdapter, ChannelError, Identity
from del_social.connections.meta import MetaClient
from del_social.connections.service import credentials, record_check, save_connection
from del_social.connections.telegram import TelegramAdapter
from del_social.core.config import get_settings
from del_social.core.db import set_tenant
from del_social.core.deps import (
    TenantContext,
    get_db,
    get_http,
    get_meta,
    get_meta_optional,
    get_redis,
    get_vault,
    get_vault_optional,
    require_permission,
)
from del_social.core.sessions import SESSION_COOKIE, resolve_session
from del_social.core.vault import TokenVault, VaultError
from del_social.models import Channel, Connection, Membership
from del_social.tenants.permissions import Permission, has_permission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants/{tenant_id}/connections", tags=["connections"])
callback_router = APIRouter(tags=["connections"])

can_view = require_permission(Permission.VIEW)
can_manage = require_permission(Permission.MANAGE_CONNECTIONS)

STATE_TTL = 600  # seconds to finish the Facebook dialog
PICK_TTL = 900  # seconds to choose a page afterwards


def _state_key(state: str) -> str:
    return f"meta_oauth:state:{state}"


def _pick_key(pick: str) -> str:
    return f"meta_oauth:pick:{pick}"


def _pick_aad(tenant_id: uuid.UUID, pick: str) -> bytes:
    return f"del-social/meta-pick/{tenant_id}/{pick}".encode()


def meta_redirect_uri() -> str:
    # Same origin as the panel: the web app proxies /api/* to this API
    return f"{get_settings().app_base_url}/api/connections/meta/callback"


class ConnectionOut(BaseModel):
    connection_id: uuid.UUID
    channel: Channel
    external_id: str
    display_name: str
    status: str
    token_expires_at: datetime | None
    last_checked_at: datetime | None
    last_error: str | None
    details: dict[str, Any]
    created_at: datetime


class ChannelOut(BaseModel):
    channel: Channel
    connect_method: str
    available: bool  # implemented in this version
    configured: bool  # the server has what it needs (vault key, Meta app)
    capabilities: dict[str, bool]
    connections: list[ConnectionOut]


class TelegramIn(BaseModel):
    bot_token: str = Field(min_length=1, max_length=100)


class StartOut(BaseModel):
    url: str


class PageOption(BaseModel):
    page_id: str
    name: str
    instagram_id: str | None
    instagram_username: str | None


class PickIn(BaseModel):
    page_id: str = Field(max_length=64)


def _out(conn: Connection) -> ConnectionOut:
    return ConnectionOut.model_validate(conn, from_attributes=True)


def _adapters(
    http: httpx.AsyncClient = Depends(get_http),
    meta: MetaClient | None = Depends(get_meta_optional),
) -> dict[Channel, ChannelAdapter]:
    return build_adapters(http, meta)


async def _get_connection(db: AsyncSession, connection_id: uuid.UUID) -> Connection:
    conn = await db.get(Connection, connection_id)  # RLS: this tenant only
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return conn


@router.get("", response_model=list[ChannelOut])
async def list_connections(
    ctx: TenantContext = Depends(can_view),
    db: AsyncSession = Depends(get_db),
    adapters: dict[Channel, ChannelAdapter] = Depends(_adapters),
    vault: TokenVault | None = Depends(get_vault_optional),
    meta: MetaClient | None = Depends(get_meta_optional),
) -> list[ChannelOut]:
    rows = (await db.scalars(select(Connection).order_by(Connection.created_at))).all()
    result = []
    for channel in CHANNELS:
        adapter = adapters[channel]
        needs_meta = channel in (Channel.FACEBOOK, Channel.INSTAGRAM)
        caps = adapter.capabilities()
        result.append(
            ChannelOut(
                channel=channel,
                connect_method=adapter.connect_method,
                available=adapter.available,
                configured=adapter.available and vault is not None and (meta is not None or not needs_meta),
                capabilities={k: getattr(caps, k) for k in ("publish", "comments", "messages", "insights")},
                connections=[_out(c) for c in rows if c.channel == channel.value],
            )
        )
    return result


@router.post("/telegram", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def connect_telegram(
    body: TelegramIn,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
    vault: TokenVault = Depends(get_vault),
    adapters: dict[Channel, ChannelAdapter] = Depends(_adapters),
) -> ConnectionOut:
    telegram = adapters[Channel.TELEGRAM]
    assert isinstance(telegram, TelegramAdapter)
    token = body.bot_token.strip()
    try:
        identity = await telegram.get_me(token)
    except ChannelError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    conn = await save_connection(
        db, vault, tenant_id=ctx.tenant_id, channel=Channel.TELEGRAM, identity=identity,
        token=token, connected_by=ctx.account.account_id,
    )
    return _out(conn)


@router.post("/{connection_id}/test", response_model=ConnectionOut)
async def test_connection(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
    vault: TokenVault = Depends(get_vault),
    adapters: dict[Channel, ChannelAdapter] = Depends(_adapters),
) -> ConnectionOut:
    conn = await _get_connection(db, connection_id)
    identity: Identity | None = None
    error: str | None = None
    try:
        identity = await adapters[Channel(conn.channel)].check(credentials(vault, conn))
    except VaultError:
        log.error("vault decrypt failed for connection %s", conn.connection_id)
        error = "The stored token could not be read. Please connect again."
    except ChannelError as e:
        error = str(e)
    return _out(await record_check(db, conn, error, identity))


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    connection_id: uuid.UUID,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.delete(await _get_connection(db, connection_id))


# --- Meta (Facebook pages + Instagram) ---


@router.post("/meta/start", response_model=StartOut)
async def meta_start(
    ctx: TenantContext = Depends(can_manage),
    redis: Redis = Depends(get_redis),
    meta: MetaClient = Depends(get_meta),
    vault: TokenVault = Depends(get_vault),
) -> StartOut:
    state = secrets.token_urlsafe(24)
    await redis.set(
        _state_key(state),
        json.dumps({"tenant_id": str(ctx.tenant_id), "account_id": str(ctx.account.account_id)}),
        ex=STATE_TTL,
    )
    return StartOut(url=meta.authorize_url(state=state, redirect_uri=meta_redirect_uri()))


@callback_router.get("/connections/meta/callback", include_in_schema=False)
async def meta_callback(
    request: Request,
    state: str = "",
    code: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    meta: MetaClient | None = Depends(get_meta_optional),
    vault: TokenVault | None = Depends(get_vault_optional),
) -> RedirectResponse:
    """Facebook sends the browser here. Always answers with a redirect back to the panel."""
    raw = await redis.getdel(_state_key(state)) if state else None  # single use
    if raw is None:
        return RedirectResponse("/?meta=expired", status_code=303)
    started = json.loads(raw)
    tenant_id = uuid.UUID(started["tenant_id"])
    back = f"/t/{tenant_id}/connections"

    # Same person, same browser, still allowed to manage connections
    token = request.cookies.get(SESSION_COOKIE)
    account_id = await resolve_session(db, token) if token else None
    if account_id is None or str(account_id) != started["account_id"]:
        return RedirectResponse(f"{back}?meta=session", status_code=303)
    await set_tenant(db, tenant_id)
    role = await db.scalar(select(Membership.role).where(Membership.account_id == account_id))
    if role is None or not has_permission(role, Permission.MANAGE_CONNECTIONS):
        return RedirectResponse(f"{back}?meta=forbidden", status_code=303)

    if error or not code:
        return RedirectResponse(f"{back}?meta=cancelled", status_code=303)
    if meta is None or vault is None:  # configuration removed mid-flow
        return RedirectResponse(f"{back}?meta=error", status_code=303)
    try:
        user_token = await meta.exchange_code(code, meta_redirect_uri())
        pages = await meta.pages(user_token)
    except ChannelError as e:
        log.warning("meta oauth failed for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{back}?meta=error", status_code=303)
    if not pages:
        return RedirectResponse(f"{back}?meta=nopages", status_code=303)

    pick = secrets.token_urlsafe(16)
    payload = json.dumps({"account_id": str(account_id), "pages": pages})
    await redis.set(_pick_key(pick), vault.encrypt(payload, aad=_pick_aad(tenant_id, pick)), ex=PICK_TTL)
    return RedirectResponse(f"{back}?meta=pick&pick={pick}", status_code=303)


async def _load_pick(redis: Redis, vault: TokenVault, ctx: TenantContext, pick: str) -> list[dict[str, Any]]:
    blob = await redis.get(_pick_key(pick))
    if blob is None:
        raise HTTPException(status.HTTP_410_GONE, "This page choice has expired. Connect again.")
    try:
        data = json.loads(vault.decrypt(blob, aad=_pick_aad(ctx.tenant_id, pick)))
    except VaultError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown page choice") from None
    if data["account_id"] != str(ctx.account.account_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown page choice")
    return data["pages"]


@router.get("/meta/pick/{pick}", response_model=list[PageOption])
async def meta_pick_options(
    pick: str,
    ctx: TenantContext = Depends(can_manage),
    redis: Redis = Depends(get_redis),
    vault: TokenVault = Depends(get_vault),
) -> list[PageOption]:
    pages = await _load_pick(redis, vault, ctx, pick)
    return [
        PageOption(
            page_id=p["id"],
            name=p["name"],
            instagram_id=(p["instagram"] or {}).get("id"),
            instagram_username=(p["instagram"] or {}).get("username"),
        )
        for p in pages
    ]


@router.post("/meta/pick/{pick}", response_model=list[ConnectionOut], status_code=status.HTTP_201_CREATED)
async def meta_pick(
    pick: str,
    body: PickIn,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    vault: TokenVault = Depends(get_vault),
) -> list[ConnectionOut]:
    pages = await _load_pick(redis, vault, ctx, pick)
    page = next((p for p in pages if p["id"] == body.page_id), None)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This page was not in the list")
    common = {"tenant_id": ctx.tenant_id, "token": page["token"], "connected_by": ctx.account.account_id}
    saved = [
        await save_connection(
            db, vault, channel=Channel.FACEBOOK,
            identity=Identity(external_id=page["id"], display_name=page["name"]), **common,
        )
    ]
    if ig := page["instagram"]:
        saved.append(
            await save_connection(
                db, vault, channel=Channel.INSTAGRAM,
                identity=Identity(
                    external_id=ig["id"],
                    display_name=f"@{ig.get('username') or ig['id']}",
                    details={"page_id": page["id"], "page_name": page["name"]},
                ),
                **common,
            )
        )
    await redis.delete(_pick_key(pick))
    return [_out(c) for c in saved]
