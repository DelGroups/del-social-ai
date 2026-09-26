"""Sends each LLM call to Langfuse (CLAUDE.md principle 9) as one OpenTelemetry span.

OTLP over HTTP/JSON to /api/public/otel/v1/traces with `x-langfuse-ingestion-version: 4`,
the ingestion path Langfuse Cloud supports after the v3 API shuts down (2026-11-16).
Attribute keys: langfuse.com/integrations/native/opentelemetry (checked 2026-09-26).

Plain HTTP instead of an SDK: one request per call, no background threads, easy to fake
in tests. Tracing must never break or slow down real work: every failure is logged
and swallowed, with a short timeout.
"""
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import httpx

from del_social.llm.pricing import Usage

log = logging.getLogger(__name__)

STATUS_ERROR = 2  # OTLP StatusCode


@dataclass(frozen=True)
class TraceRecord:
    trace_id: str  # 32 hex chars (OpenTelemetry trace id); also stored in llm_calls
    tenant_id: uuid.UUID | None
    agent: str
    prompt_name: str
    prompt_version: int
    prompt_ref: str
    model: str
    input: str
    output: str | None
    error: str | None
    usage: Usage
    cost_usd: Decimal | None
    started: datetime
    ended: datetime


def _nanos(t: datetime) -> str:
    return str(int(t.timestamp() * 1_000_000_000))


def _attr(key: str, value: str | int | list[str]) -> dict:
    if isinstance(value, list):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": v} for v in value]}}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def otlp_payload(r: TraceRecord) -> dict:
    tenant = str(r.tenant_id) if r.tenant_id else None
    usage = {
        "input": r.usage.input_tokens,
        "output": r.usage.output_tokens,
        "cache_read_input_tokens": r.usage.cache_read_tokens,
        "cache_creation_input_tokens": r.usage.cache_write_tokens,
    }
    attrs = [
        _attr("langfuse.trace.name", r.agent),
        _attr("langfuse.trace.tags", [f"tenant:{tenant}" if tenant else "platform", f"agent:{r.agent}"]),
        _attr("langfuse.observation.type", "generation"),
        _attr("langfuse.observation.model.name", r.model),
        _attr("langfuse.observation.input", r.input),
        _attr("langfuse.observation.usage_details", json.dumps(usage)),
        _attr("langfuse.observation.prompt.name", r.prompt_name),
        _attr("langfuse.observation.prompt.version", r.prompt_version),
        _attr("langfuse.observation.metadata.prompt_ref", r.prompt_ref),
    ]
    if tenant:
        attrs += [_attr("langfuse.user.id", tenant), _attr("langfuse.trace.metadata.tenant_id", tenant)]
    if r.output is not None:
        attrs.append(_attr("langfuse.observation.output", r.output))
    if r.cost_usd is not None:
        attrs.append(_attr("langfuse.observation.cost_details", json.dumps({"total": float(r.cost_usd)})))
    if r.error:
        attrs += [_attr("langfuse.observation.level", "ERROR"), _attr("langfuse.observation.status_message", r.error)]
    span = {
        "traceId": r.trace_id,
        "spanId": secrets.token_hex(8),
        "name": r.agent,
        "kind": 1,
        "startTimeUnixNano": _nanos(r.started),
        "endTimeUnixNano": _nanos(r.ended),
        "attributes": attrs,
    }
    if r.error:
        span["status"] = {"code": STATUS_ERROR, "message": r.error}
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", "del-social-api")]},
                "scopeSpans": [{"scope": {"name": "del_social.llm"}, "spans": [span]}],
            }
        ]
    }


class Tracer:
    def __init__(self, http: httpx.AsyncClient, host: str, public_key: str, secret_key: str):
        self._http = http
        self._url = host.rstrip("/") + "/api/public/otel/v1/traces"
        self._auth = (public_key, secret_key)

    def __repr__(self) -> str:
        return f"Tracer(url={self._url!r})"

    async def send(self, r: TraceRecord) -> None:
        try:
            resp = await self._http.post(
                self._url,
                json=otlp_payload(r),
                auth=self._auth,
                headers={"x-langfuse-ingestion-version": "4"},
                timeout=5.0,
            )
            if resp.status_code >= 300:
                log.warning("langfuse otel ingestion returned %s", resp.status_code)
        except httpx.HTTPError as e:
            log.warning("langfuse otel ingestion failed: %s", type(e).__name__)
