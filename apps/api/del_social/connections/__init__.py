"""Channel adapters and the registry that builds them."""
import httpx

from del_social.connections.base import ChannelAdapter, TikTokAdapter, WhatsAppAdapter
from del_social.connections.meta import FacebookAdapter, InstagramAdapter, MetaClient
from del_social.connections.telegram import TelegramAdapter
from del_social.connections.youtube import YouTubeAdapter, YouTubeClient
from del_social.models import Channel

# Display order in the panel
CHANNELS = (
    Channel.INSTAGRAM,
    Channel.FACEBOOK,
    Channel.TELEGRAM,
    Channel.WHATSAPP,
    Channel.TIKTOK,
    Channel.YOUTUBE,
)


def build_adapters(
    http: httpx.AsyncClient, meta: MetaClient | None, yt: YouTubeClient | None = None
) -> dict[Channel, ChannelAdapter]:
    adapters: list[ChannelAdapter] = [
        InstagramAdapter(meta),
        FacebookAdapter(meta),
        TelegramAdapter(http),
        WhatsAppAdapter(),
        TikTokAdapter(),
        YouTubeAdapter(yt),
    ]
    return {a.channel: a for a in adapters}
