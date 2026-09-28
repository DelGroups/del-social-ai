"""Google sign-in and the YouTube APIs (ADR 012): the only code that talks to YouTube.

- OAuth 2.0 web-server flow with offline access: we keep the refresh token (encrypted, ADR 003)
  and ask Google for a short-lived access token when we need one (cached in memory until expiry).
- YouTube Data API v3 (videos, thumbnails, captions, comments, playlists, charts, search) and
  YouTube Analytics API v2 (views, watch time, retention, traffic, audience, revenue).
- Every Data API call is counted in units against the project's daily budget (it resets at midnight
  Pacific time). We stop at STOP_AT of the budget so the project is never blocked, and expensive
  calls (search) stop earlier.
Errors carry Google's reason (quotaExceeded, forbidden, …) and never a token.
"""
import hashlib
import logging
import time
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from del_social.connections.base import Capabilities, ChannelAdapter, ChannelError, Credentials, Identity
from del_social.models import Channel

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DATA = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
)
# Quota cost of each Data API method (developers.google.com/youtube/v3/determine_quota_cost)
UNITS = {
    "list": 1, "search": 100, "update": 50, "insert": 50, "delete": 50, "thumbnail": 50,
    "caption_download": 200, "caption_insert": 400, "upload": 1600, "moderate": 50, "rate": 50,
}
STOP_AT = 0.9  # share of the daily budget after which only cheap reads continue
SEARCH_STOP_AT = 0.6  # search is rationed harder
PACIFIC = timezone(timedelta(hours=-8))  # the quota day; an hour off in summer is harmless here


class YouTubeError(ChannelError):
    """A Google call failed. The message is safe to show (never a token)."""

    def __init__(self, message: str, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason

    @property
    def auth(self) -> bool:
        """The connection must be made again (token expired or access removed)."""
        return self.status == 401 or self.reason in ("invalid_grant", "authError", "unauthorized_client")


class QuotaMeter:
    """Data API units used today, per Google project (in memory; one API process)."""

    def __init__(self, daily_units: int):
        self.daily = daily_units
        self._day: date | None = None
        self.used = 0

    def _today(self) -> date:
        return datetime.now(PACIFIC).date()

    def spend(self, units: int, kind: str) -> None:
        today = self._today()
        if today != self._day:
            self._day, self.used = today, 0
        limit = self.daily * (SEARCH_STOP_AT if kind == "search" else STOP_AT)
        if units > 1 and self.used + units > limit:
            raise YouTubeError("Today's YouTube API budget is used up; this continues after 11:00 Baku time.", 429, "localQuota")
        self.used += units


class GoogleOAuth:
    def __init__(self, http: httpx.AsyncClient, client_id: str, client_secret: str):
        self._http = http
        self._id = client_id
        self._secret = client_secret

    def __repr__(self) -> str:
        return "GoogleOAuth()"

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(SCOPES),
            "access_type": "offline", "prompt": "consent select_account", "include_granted_scopes": "true", "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _token(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            r = await self._http.post(TOKEN_URL, data={**data, "client_id": self._id, "client_secret": self._secret}, timeout=30.0)
            body = r.json()
        except (httpx.HTTPError, ValueError):
            raise YouTubeError("Google could not be reached") from None
        if r.status_code >= 400 or "error" in body:
            reason = body.get("error") if isinstance(body, dict) else None
            text = "Google no longer accepts this connection; connect the channel again" if reason == "invalid_grant" \
                else f"Google refused the sign-in ({reason or r.status_code})"
            raise YouTubeError(text, r.status_code, reason)
        return body

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """{"access_token", "refresh_token", "expires_in", "scope"}."""
        return await self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    async def revoke(self, token: str) -> None:
        try:
            await self._http.post(REVOKE_URL, data={"token": token}, timeout=15.0)
        except httpx.HTTPError:
            pass


class YouTubeClient:
    def __init__(self, http: httpx.AsyncClient, oauth: GoogleOAuth, meter: QuotaMeter):
        self._http = http
        self.oauth = oauth
        self.meter = meter
        self._access: dict[str, tuple[str, float]] = {}

    def __repr__(self) -> str:
        return "YouTubeClient()"

    async def access_token(self, creds: Credentials) -> str:
        key = hashlib.sha256(creds.token.encode()).hexdigest()
        cached = self._access.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        body = await self.oauth.refresh(creds.token)
        token = body["access_token"]
        self._access[key] = (token, time.monotonic() + int(body.get("expires_in", 3600)) - 120)
        return token

    async def _call(
        self, method: str, url: str, creds: Credentials, *, units: int = 0, kind: str = "list",
        params: dict[str, Any] | None = None, json: Any = None, content: bytes | None = None,
        headers: dict[str, str] | None = None, timeout: float = 60.0,
    ) -> dict[str, Any]:
        if units:
            self.meter.spend(units, kind)
        token = await self.access_token(creds)
        try:
            r = await self._http.request(
                method, url, params=params, json=json, content=content, timeout=timeout,
                headers={"Authorization": f"Bearer {token}", **(headers or {})},
            )
            body = r.json() if r.content else {}
        except (httpx.HTTPError, ValueError):
            raise YouTubeError("YouTube could not be reached") from None
        if r.status_code >= 400:
            err = body.get("error") if isinstance(body, dict) else None
            err = err if isinstance(err, dict) else {}
            reason = ((err.get("errors") or [{}])[0] or {}).get("reason") or err.get("status")
            raise YouTubeError(f"YouTube: {(err.get('message') or 'request refused')[:300]}", r.status_code, reason)
        return body

    async def data(self, method: str, path: str, creds: Credentials, units: int, kind: str = "list", **kw: Any) -> dict[str, Any]:
        return await self._call(method, f"{DATA}/{path}", creds, units=units, kind=kind, **kw)

    # --- channel and videos ---

    async def my_channel(self, creds: Credentials) -> dict[str, Any]:
        d = await self.data("GET", "channels", creds, 1, params={
            "part": "snippet,statistics,contentDetails,brandingSettings,status", "mine": "true",
        })
        items = d.get("items") or []
        if not items:
            raise YouTubeError("This Google account has no YouTube channel", 404, "noChannel")
        return items[0]

    async def channels(self, creds: Credentials, *, ids: list[str] | None = None, handle: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"part": "snippet,statistics,contentDetails"}
        if handle:
            params["forHandle"] = handle if handle.startswith("@") else f"@{handle}"
        else:
            params["id"] = ",".join(ids or [])
        return (await self.data("GET", "channels", creds, 1, params=params)).get("items") or []

    async def playlist_video_ids(self, creds: Credentials, playlist_id: str, limit: int = 50) -> list[str]:
        ids: list[str] = []
        token = None
        while len(ids) < limit:
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": str(min(50, limit - len(ids)))}
            if token:
                params["pageToken"] = token
            d = await self.data("GET", "playlistItems", creds, 1, params=params)
            ids += [i["contentDetails"]["videoId"] for i in d.get("items") or []]
            token = d.get("nextPageToken")
            if not token:
                break
        return ids

    async def videos(self, creds: Credentials, ids: list[str], parts: str = "snippet,statistics,contentDetails,status") -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(ids), 50):
            d = await self.data("GET", "videos", creds, 1, params={"part": parts, "id": ",".join(ids[i:i + 50])})
            out += d.get("items") or []
        return out

    async def update_video(self, creds: Credentials, video: dict[str, Any], parts: str) -> dict[str, Any]:
        """videos.update replaces every field of the parts sent: always send the full, merged resource."""
        return await self.data("PUT", "videos", creds, UNITS["update"], kind="update", params={"part": parts}, json=video)

    async def set_thumbnail(self, creds: Credentials, video_id: str, jpeg: bytes) -> dict[str, Any]:
        return await self._call("POST", f"{UPLOAD}/thumbnails/set", creds, units=UNITS["thumbnail"], kind="update",
                                params={"videoId": video_id, "uploadType": "media"}, content=jpeg,
                                headers={"Content-Type": "image/jpeg"})

    async def most_popular(self, creds: Credentials, region: str, category: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        params = {"part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": region, "maxResults": str(limit)}
        if category:
            params["videoCategoryId"] = category
        try:
            return (await self.data("GET", "videos", creds, 1, params=params)).get("items") or []
        except YouTubeError as e:
            if e.status in (400, 404):  # the chart does not exist for this region/category
                return []
            raise

    async def search(self, creds: Credentials, q: str, *, region: str | None = None, language: str | None = None,
                     published_after: datetime | None = None, order: str = "viewCount", limit: int = 15) -> list[str]:
        """Video ids for a query (100 units: rationed)."""
        params = {"part": "id", "q": q, "type": "video", "order": order, "maxResults": str(limit)}
        if region:
            params["regionCode"] = region
        if language:
            params["relevanceLanguage"] = language
        if published_after:
            params["publishedAfter"] = published_after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        d = await self.data("GET", "search", creds, UNITS["search"], kind="search", params=params)
        return [i["id"]["videoId"] for i in d.get("items") or [] if i.get("id", {}).get("videoId")]

    # --- captions ---

    async def captions(self, creds: Credentials, video_id: str) -> list[dict[str, Any]]:
        return (await self.data("GET", "captions", creds, 50, kind="list", params={"part": "snippet", "videoId": video_id})).get("items") or []

    async def caption_text(self, creds: Credentials, caption_id: str) -> str:
        """The track as SRT (only for videos of the connected channel)."""
        self.meter.spend(UNITS["caption_download"], "update")
        token = await self.access_token(creds)
        try:
            r = await self._http.get(f"{DATA}/captions/{caption_id}", params={"tfmt": "srt"},
                                     headers={"Authorization": f"Bearer {token}"}, timeout=60.0)
        except httpx.HTTPError:
            raise YouTubeError("YouTube could not be reached") from None
        if r.status_code >= 400:
            raise YouTubeError("YouTube did not give the subtitles of this video", r.status_code, "captionDownload")
        return r.text

    async def insert_caption(self, creds: Credentials, video_id: str, language: str, name: str, srt: str) -> dict[str, Any]:
        """A subtitle track (multipart upload: metadata + SRT)."""
        import json as _json

        boundary = "delsocialcaption"
        meta = _json.dumps({"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}})
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                f"--{boundary}\r\nContent-Type: application/x-subrip\r\n\r\n{srt}\r\n--{boundary}--").encode()
        return await self._call("POST", f"{UPLOAD}/captions", creds, units=UNITS["caption_insert"], kind="update",
                                params={"part": "snippet", "uploadType": "multipart"}, content=body,
                                headers={"Content-Type": f"multipart/related; boundary={boundary}"})

    # --- comments ---

    async def comment_threads(self, creds: Credentials, *, channel_id: str | None = None, video_id: str | None = None,
                              limit: int = 50) -> list[dict[str, Any]]:
        params = {"part": "snippet", "maxResults": str(min(100, limit)), "order": "time", "textFormat": "plainText"}
        if video_id:
            params["videoId"] = video_id
        else:
            params["allThreadsRelatedToChannelId"] = channel_id or ""
        return (await self.data("GET", "commentThreads", creds, 1, params=params)).get("items") or []

    async def reply(self, creds: Credentials, parent_id: str, text: str) -> dict[str, Any]:
        return await self.data("POST", "comments", creds, UNITS["insert"], kind="update", params={"part": "snippet"},
                               json={"snippet": {"parentId": parent_id, "textOriginal": text}})

    # --- playlists ---

    async def playlists(self, creds: Credentials) -> list[dict[str, Any]]:
        return (await self.data("GET", "playlists", creds, 1, params={"part": "snippet,contentDetails", "mine": "true", "maxResults": "50"})).get("items") or []

    async def add_to_playlist(self, creds: Credentials, playlist_id: str, video_id: str) -> dict[str, Any]:
        return await self.data("POST", "playlistItems", creds, UNITS["insert"], kind="update", params={"part": "snippet"},
                               json={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})

    # --- analytics ---

    async def report(self, creds: Credentials, *, start: date, end: date, metrics: str, dimensions: str | None = None,
                     filters: str | None = None, sort: str | None = None, limit: int | None = None) -> dict[str, Any]:
        """One Analytics query → {"columns": [...], "rows": [[...]]} (no Data API units)."""
        params = {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(), "metrics": metrics}
        for k, v in (("dimensions", dimensions), ("filters", filters), ("sort", sort), ("maxResults", limit)):
            if v:
                params[k] = str(v)
        d = await self._call("GET", ANALYTICS, creds, params=params)
        cols = [h["name"] for h in d.get("columnHeaders") or []]
        return {"columns": cols, "rows": d.get("rows") or []}


def rows_as_dicts(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(report["columns"], r)) for r in report["rows"]]


def channel_identity(ch: dict[str, Any]) -> Identity:
    sn = ch.get("snippet") or {}
    thumbs = sn.get("thumbnails") or {}
    return Identity(
        external_id=ch["id"],
        display_name=sn.get("title") or ch["id"],
        details={
            "handle": sn.get("customUrl"),
            "avatar": ((thumbs.get("medium") or thumbs.get("default") or {}).get("url")),
            "uploads": ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads"),
            "country": sn.get("country"),
            "language": sn.get("defaultLanguage"),
        },
    )


class YouTubeAdapter(ChannelAdapter):
    channel = Channel.YOUTUBE
    connect_method = "oauth"
    available = True

    def __init__(self, yt: YouTubeClient | None):
        self._yt = yt

    def capabilities(self) -> Capabilities:
        return Capabilities(publish=True, comments=True, insights=True)

    async def check(self, creds: Credentials) -> Identity:
        if self._yt is None:
            raise ChannelError("Google sign-in is not configured on this server")
        return channel_identity(await self._yt.my_channel(creds))
