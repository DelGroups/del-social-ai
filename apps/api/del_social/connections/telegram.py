"""Telegram bot channel: connected with a bot token from @BotFather."""
import re

import httpx

from del_social.connections.base import Capabilities, ChannelAdapter, ChannelError, Credentials, Identity
from del_social.models import Channel

API = "https://api.telegram.org"
BOT_TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")


class TelegramAdapter(ChannelAdapter):
    channel = Channel.TELEGRAM
    connect_method = "bot_token"
    available = True

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    def capabilities(self) -> Capabilities:
        return Capabilities(publish=True, messages=True)

    async def get_me(self, token: str) -> Identity:
        if not BOT_TOKEN_RE.match(token):
            raise ChannelError("This does not look like a Telegram bot token")
        # The token is part of the URL: errors are re-raised without httpx's message,
        # and the httpx logger is kept at WARNING (main.py) so URLs are never logged.
        try:
            r = await self._http.get(f"{API}/bot{token}/getMe")
            data = r.json()
        except (httpx.HTTPError, ValueError):
            raise ChannelError("Telegram could not be reached") from None
        if not data.get("ok"):
            raise ChannelError("Telegram rejected this bot token")
        bot = data["result"]
        return Identity(
            external_id=str(bot["id"]),
            display_name=f"@{bot['username']}",
            details={"bot_name": bot.get("first_name", "")},
        )

    async def check(self, creds: Credentials) -> Identity:
        identity = await self.get_me(creds.token)
        if identity.external_id != creds.external_id:
            raise ChannelError("This token now belongs to a different bot")
        return identity
