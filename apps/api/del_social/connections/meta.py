"""Facebook pages and Instagram professional accounts through the Meta Graph API.

One OAuth login ("Connect with Meta") yields a long-lived user token; from it we read the
pages the person manages, each with its own page token and linked Instagram account.
Page tokens obtained this way do not expire; the Instagram account uses its page's token.
"""
import hashlib
import hmac
from typing import Any
from urllib.parse import urlencode

import httpx

from del_social.connections.base import Capabilities, ChannelAdapter, ChannelError, Credentials, Identity
from del_social.models import Channel

# Requested when the app uses classic Facebook Login. With Facebook Login for Business the
# permissions come from the login configuration (META_LOGIN_CONFIG_ID) instead.
SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_read_user_content",
    "pages_manage_posts",
    "pages_manage_metadata",
    "pages_manage_engagement",
    "pages_messaging",
    "read_insights",
    "business_management",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_comments",
    "instagram_manage_insights",
    "instagram_manage_messages",
)
PAGE_FIELDS = "id,name,access_token,instagram_business_account{id,username,name}"


class MetaError(ChannelError):
    pass


class MetaClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        app_id: str,
        app_secret: str,
        version: str,
        login_config_id: str = "",
    ):
        self._http = http
        self._app_id = app_id
        self._secret = app_secret
        self._version = version
        self._config_id = login_config_id
        self._graph = f"https://graph.facebook.com/{version}"

    def __repr__(self) -> str:
        return f"MetaClient(app_id={self._app_id!r}, version={self._version!r})"

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        params = {"client_id": self._app_id, "redirect_uri": redirect_uri, "state": state, "response_type": "code"}
        if self._config_id:
            params |= {"config_id": self._config_id, "override_default_response_type": "true"}
        else:
            params["scope"] = ",".join(SCOPES)
        return f"https://www.facebook.com/{self._version}/dialog/oauth?{urlencode(params)}"

    def _proof(self, token: str) -> str:
        # appsecret_proof: a stolen token alone can't be used against our app
        return hmac.new(self._secret.encode(), token.encode(), hashlib.sha256).hexdigest()

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            r = await self._http.get(f"{self._graph}/{path}", params=params)
            data = r.json()
        except (httpx.HTTPError, ValueError):
            raise MetaError("Meta could not be reached") from None
        if r.status_code >= 400 or "error" in data:
            message = (data.get("error") or {}).get("message") or "Meta rejected the request"
            raise MetaError(message[:300])
        return data

    async def api(self, path: str, token: str, **params: str) -> dict[str, Any]:
        return await self._get(path, {**params, "access_token": token, "appsecret_proof": self._proof(token)})

    async def post(self, path: str, token: str, **data: str) -> dict[str, Any]:
        """A write call (publish, update). The token goes in the form body, never in a logged URL."""
        try:
            r = await self._http.post(
                f"{self._graph}/{path}",
                data={**data, "access_token": token, "appsecret_proof": self._proof(token)},
            )
            body = r.json()
        except (httpx.HTTPError, ValueError):
            raise MetaError("Meta could not be reached") from None
        if r.status_code >= 400 or "error" in body:
            message = (body.get("error") or {}).get("message") or "Meta rejected the request"
            raise MetaError(message[:300])
        return body

    async def exchange_code(self, code: str, redirect_uri: str) -> str:
        """Authorization code → long-lived user token (~60 days)."""
        short = await self._get(
            "oauth/access_token",
            {"client_id": self._app_id, "client_secret": self._secret, "redirect_uri": redirect_uri, "code": code},
        )
        long = await self._get(
            "oauth/access_token",
            {
                "grant_type": "fb_exchange_token",
                "client_id": self._app_id,
                "client_secret": self._secret,
                "fb_exchange_token": short["access_token"],
            },
        )
        return long["access_token"]

    async def pages(self, user_token: str) -> list[dict[str, Any]]:
        """Pages this person manages: id, name, page token, linked Instagram account (or None)."""
        data = await self.api("me/accounts", user_token, fields=PAGE_FIELDS, limit="100")
        return [
            {
                "id": p["id"],
                "name": p.get("name", p["id"]),
                "token": p["access_token"],
                "instagram": p.get("instagram_business_account"),
            }
            for p in data.get("data", [])
            if p.get("access_token")
        ]


class FacebookAdapter(ChannelAdapter):
    channel = Channel.FACEBOOK
    connect_method = "oauth"
    available = True

    def __init__(self, meta: MetaClient | None):
        self._meta = meta

    def capabilities(self) -> Capabilities:
        return Capabilities(publish=True, comments=True, messages=True, insights=True)

    def _client(self) -> MetaClient:
        if self._meta is None:
            raise ChannelError("The Meta app is not configured on this server")
        return self._meta

    async def check(self, creds: Credentials) -> Identity:
        page = await self._client().api(creds.external_id, creds.token, fields="id,name")
        return Identity(external_id=page["id"], display_name=page.get("name", page["id"]))


class InstagramAdapter(FacebookAdapter):
    channel = Channel.INSTAGRAM

    async def check(self, creds: Credentials) -> Identity:
        ig = await self._client().api(creds.external_id, creds.token, fields="id,username")
        return Identity(external_id=ig["id"], display_name=f"@{ig.get('username', ig['id'])}")
