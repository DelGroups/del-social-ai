"""Sends each LLM call to Langfuse (CLAUDE.md principle 9) through its public ingestion API.

Plain HTTP instead of the SDK: one request per call, no background threads, easy to fake
in tests. Tracing must never break or slow down real work: every failure is logged
and swallowed, with a short timeout.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import httpx

from del_social.llm.pricing import Usage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceRecord:
    trace_id: str
    tenant_id: uuid.UUID | None
    agent: str
    prompt_ref: str
    model: str
    input: str
    output: str | None
    error: str | None
    usage: Usage
    cost_usd: Decimal | None
    started: datetime
    ended: datetime


class Tracer:
    def __init__(self, http: httpx.AsyncClient, host: str, public_key: str, secret_key: str):
        self._http = http
        self._url = host.rstrip("/") + "/api/public/ingestion"
        self._auth = (public_key, secret_key)

    def __repr__(self) -> str:
        return f"Tracer(url={self._url!r})"

    async def send(self, r: TraceRecord) -> None:
        ts = r.ended.isoformat()
        tags = [f"tenant:{r.tenant_id}" if r.tenant_id else "platform", f"agent:{r.agent}"]
        batch = [
            {
                "id": str(uuid.uuid4()),
                "timestamp": ts,
                "type": "trace-create",
                "body": {
                    "id": r.trace_id,
                    "name": r.agent,
                    "userId": str(r.tenant_id) if r.tenant_id else None,  # Langfuse groups by tenant
                    "tags": tags,
                    "metadata": {"prompt": r.prompt_ref},
                },
            },
            {
                "id": str(uuid.uuid4()),
                "timestamp": ts,
                "type": "generation-create",
                "body": {
                    "id": str(uuid.uuid4()),
                    "traceId": r.trace_id,
                    "name": r.agent,
                    "model": r.model,
                    "input": r.input,
                    "output": r.output,
                    "level": "ERROR" if r.error else "DEFAULT",
                    "statusMessage": r.error,
                    "startTime": r.started.isoformat(),
                    "endTime": ts,
                    "usageDetails": {
                        "input": r.usage.input_tokens,
                        "output": r.usage.output_tokens,
                        "cache_read_input_tokens": r.usage.cache_read_tokens,
                        "cache_creation_input_tokens": r.usage.cache_write_tokens,
                    },
                    "costDetails": {"total": float(r.cost_usd)} if r.cost_usd is not None else None,
                    "metadata": {"prompt": r.prompt_ref, "tenant_id": str(r.tenant_id) if r.tenant_id else None},
                },
            },
        ]
        try:
            resp = await self._http.post(self._url, json={"batch": batch}, auth=self._auth, timeout=5.0)
            if resp.status_code >= 300:
                log.warning("langfuse ingestion returned %s", resp.status_code)
        except httpx.HTTPError as e:
            log.warning("langfuse ingestion failed: %s", type(e).__name__)
