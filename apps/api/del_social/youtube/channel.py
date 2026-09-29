"""The connected YouTube channel of a company, its settings, and the owner's report language."""
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.base import Credentials
from del_social.connections.service import credentials
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.models import Channel, Connection, YtSettings
from del_social.team import texts

LANGS = ("az", "ru", "en", "tr")


class Settings(BaseModel):
    """What the owner tells the team about the channel, and how often they want reports."""

    about: str = Field(default="", max_length=1500)  # topic, format, what makes it different
    audience: str = Field(default="", max_length=800)
    tone: str = Field(default="", max_length=400)  # the creator's voice for replies and descriptions
    languages: list[Literal["az", "ru", "en", "tr"]] = Field(default_factory=lambda: ["az"], min_length=1, max_length=4)
    region: str = Field(default="AZ", pattern="^[A-Z]{2}$")  # the audience's country (trends)
    pulse_hours: Literal[0, 3, 6, 12] = 6  # 0 = no pulse
    daily_report: bool = True
    daily_at: int = Field(default=9, ge=0, le=23)  # hour, Baku time
    report_language: Literal["auto", "az", "ru", "en", "fa"] = "auto"
    links: str = Field(default="", max_length=1000)  # always kept at the end of descriptions
    competitors: list[str] = Field(default_factory=list, max_length=15)  # handles or channel ids


@dataclass(frozen=True)
class Studio:
    """One connected channel, loaded for a piece of work."""

    tenant_id: uuid.UUID
    connection: Connection
    settings: Settings

    @property
    def connection_id(self) -> uuid.UUID:
        return self.connection.connection_id

    @property
    def uploads(self) -> str | None:
        return (self.connection.details or {}).get("uploads")

    def channel_block(self) -> dict[str, Any]:
        d = self.connection.details or {}
        s = self.settings
        return {"name": self.connection.display_name, "handle": d.get("handle"), "about": s.about, "audience": s.audience,
                "tone": s.tone, "languages": s.languages, "country": s.region}


async def youtube_connection(db: AsyncSession) -> Connection | None:
    return await db.scalar(select(Connection).where(Connection.channel == Channel.YOUTUBE.value).order_by(Connection.created_at).limit(1))


async def settings_of(db: AsyncSession, connection_id: uuid.UUID) -> Settings:
    row = await db.get(YtSettings, connection_id)
    return Settings.model_validate(row.data if row else {})


async def save_settings(db: AsyncSession, tenant_id: uuid.UUID, connection_id: uuid.UUID, s: Settings) -> Settings:
    row = await db.get(YtSettings, connection_id)
    if row is None:
        row = YtSettings(connection_id=connection_id, tenant_id=tenant_id)
        db.add(row)
    row.data = s.model_dump()
    await db.flush()
    return s


async def load(engine: AsyncEngine, tenant_id: uuid.UUID) -> Studio | None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        conn = await youtube_connection(db)
        if conn is None:
            return None
        return Studio(tenant_id, conn, await settings_of(db, conn.connection_id))


def creds(vault: TokenVault, studio: Studio) -> Credentials:
    return credentials(vault, studio.connection)


async def report_language(db: AsyncSession, s: Settings) -> str:
    return s.report_language if s.report_language != "auto" else await texts.language_of(db)
