"""The one interface every channel implements (CLAUDE.md, "Channel adapter contract").

Adapters are the only code that talks to a social network. They receive the decrypted
token from the connections service and never read or write the database themselves.
Phase 0 implements connect + check; publishing, comments, messages and insights arrive
with the agents in Phase 1-2 and raise NotSupported until then.
"""
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from del_social.models import Channel

ConnectMethod = Literal["oauth", "bot_token", "embedded_signup"]


class ChannelError(Exception):
    """A channel call failed. The message is safe to show to the user (never contains tokens)."""


class NotConnected(ChannelError):
    pass


class NotSupported(ChannelError):
    pass


@dataclass(frozen=True)
class Capabilities:
    publish: bool = False
    comments: bool = False
    messages: bool = False
    insights: bool = False


@dataclass(frozen=True)
class Credentials:
    """What an adapter needs to act for one connection. Built by the service, never persisted."""

    external_id: str
    token: str
    details: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # never show the token in logs or tracebacks
        return f"Credentials(external_id={self.external_id!r})"


@dataclass(frozen=True)
class Identity:
    """Who a token belongs to, as reported by the channel."""

    external_id: str
    display_name: str
    details: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter:
    channel: ClassVar[Channel]
    connect_method: ClassVar[ConnectMethod]
    available: ClassVar[bool] = False  # False = shown as "coming soon"

    def capabilities(self) -> Capabilities:
        return Capabilities()

    async def check(self, creds: Credentials) -> Identity:
        """Test button: prove the stored token still works. Raises ChannelError otherwise."""
        raise NotConnected(f"{self.channel} is not available yet")

    async def refresh(self, creds: Credentials) -> str | None:
        """New token if this channel's tokens expire; None when nothing needs refreshing."""
        return None

    async def publish(self, creds: Credentials, post: Any) -> str:
        raise NotSupported(f"Publishing to {self.channel} is not supported yet")

    async def fetch_comments(self, creds: Credentials, since: Any = None) -> list[Any]:
        raise NotSupported(f"Reading {self.channel} comments is not supported yet")

    async def reply_comment(self, creds: Credentials, comment_id: str, text: str) -> str:
        raise NotSupported(f"Replying on {self.channel} is not supported yet")

    async def fetch_messages(self, creds: Credentials, since: Any = None) -> list[Any]:
        raise NotSupported(f"Reading {self.channel} messages is not supported yet")

    async def send_message(self, creds: Credentials, recipient_id: str, text: str) -> str:
        raise NotSupported(f"Sending {self.channel} messages is not supported yet")

    async def insights(self, creds: Credentials, since: Any = None) -> dict[str, Any]:
        raise NotSupported(f"{self.channel} insights are not supported yet")


class WhatsAppAdapter(ChannelAdapter):
    channel = Channel.WHATSAPP
    connect_method = "embedded_signup"


class TikTokAdapter(ChannelAdapter):
    channel = Channel.TIKTOK
    connect_method = "oauth"


class YouTubeAdapter(ChannelAdapter):
    channel = Channel.YOUTUBE
    connect_method = "oauth"
