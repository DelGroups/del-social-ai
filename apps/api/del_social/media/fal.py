"""fal.ai queue client: submit a job, wait for it, fetch the result (fal.ai/docs → Queue).

POST https://queue.fal.run/<model>  →  {request_id, status_url, response_url}
GET  status_url → IN_QUEUE | IN_PROGRESS | COMPLETED (+ error)   GET response_url → output
Errors never include the key; the key is sent only in the Authorization header.
"""
import asyncio
import time
from typing import Any

import httpx

QUEUE = "https://queue.fal.run"


class FalError(Exception):
    """Safe to show to the user."""


class FalClient:
    def __init__(self, http: httpx.AsyncClient, key: str, poll_seconds: float = 3.0, timeout_seconds: float = 300.0):
        self._http = http
        self._headers = {"Authorization": f"Key {key}"}
        self._poll = poll_seconds
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        return "FalClient()"

    async def _json(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        try:
            r = await self._http.request(method, url, headers=self._headers, timeout=60.0, **kw)
            data = r.json()
        except (httpx.HTTPError, ValueError):
            raise FalError("fal.ai could not be reached") from None
        if r.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise FalError(f"fal.ai rejected the request ({r.status_code}){': ' + str(detail)[:200] if detail else ''}")
        return data

    async def run(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = await self._json("POST", f"{QUEUE}/{model}", json=payload)
        status_url, response_url = job.get("status_url"), job.get("response_url")
        if not status_url or not response_url:
            raise FalError("fal.ai returned no job id")
        deadline = time.monotonic() + self._timeout
        while True:
            status = await self._json("GET", status_url)
            if status.get("error"):
                raise FalError(f"The image model failed: {str(status['error'])[:200]}")
            if status.get("status") == "COMPLETED":
                break
            if time.monotonic() > deadline:
                raise FalError("The image model took too long")
            await asyncio.sleep(self._poll)
        return await self._json("GET", response_url)

    async def download(self, url: str, max_bytes: int) -> bytes:
        try:
            r = await self._http.get(url, timeout=60.0)
        except httpx.HTTPError:
            raise FalError("The edited image could not be downloaded") from None
        if r.status_code != 200 or len(r.content) > max_bytes:
            raise FalError("The edited image could not be downloaded")
        return r.content
