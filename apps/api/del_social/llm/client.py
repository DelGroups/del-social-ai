"""The only way agents call an LLM (CLAUDE.md principles 2 and 9).

Every call:
- uses a versioned prompt file as the system prompt (cached by the API);
- returns a validated Pydantic object via structured outputs (output_config.format),
  never free text;
- is recorded in llm_calls for its tenant (tokens, cost computed by code, latency)
  and traced to Langfuse, whether it succeeds or fails.
"""
import enum
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Generic, TypeVar

import anthropic
from anthropic.lib._parse._transform import transform_schema
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.config import Settings
from del_social.core.db import set_tenant
from del_social.llm.pricing import Usage, cost_usd
from del_social.llm.prompts import Prompt
from del_social.llm.tracing import TraceRecord, Tracer
from del_social.models import LlmCall

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class Tier(enum.StrEnum):
    FAST = "fast"
    DEFAULT = "default"
    STRATEGY = "strategy"


class LLMError(Exception):
    """The call failed or returned nothing usable. Safe to show; never contains keys."""


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    output: T
    model: str
    usage: Usage
    cost_usd: Decimal | None
    latency_ms: int
    trace_id: str


def model_for(settings: Settings, tier: Tier) -> str:
    return {
        Tier.FAST: settings.claude_model_fast,
        Tier.DEFAULT: settings.claude_model_default,
        Tier.STRATEGY: settings.claude_model_strategy,
    }[tier]


def _usage(resp: object) -> Usage:
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage()
    return Usage(
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


def _validate(resp: object, output: type[T]) -> tuple[T | None, str | None]:
    """The JSON text block → output model, or a short reason (never the content itself)."""
    stop = getattr(resp, "stop_reason", None)
    text = "".join(b.text for b in getattr(resp, "content", []) if getattr(b, "type", None) == "text")
    if stop == "max_tokens":
        return None, "Output cut off at max_tokens"
    if stop == "refusal":
        return None, "The model refused this request"
    if not text:
        return None, f"No structured output (stop_reason={stop})"
    try:
        return output.model_validate_json(text), None
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        return None, f"Invalid structured output at {where or 'root'}: {first.get('type')}"


class LLM:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        settings: Settings,
        engine: AsyncEngine | None,
        tracer: Tracer | None,
    ):
        self._client = client
        self._settings = settings
        self._engine = engine  # None: don't record (platform checks without a tenant)
        self._tracer = tracer

    async def structured(
        self,
        *,
        tenant_id: uuid.UUID | None,
        prompt: Prompt,
        user: str,
        output: type[T],
        tier: Tier = Tier.DEFAULT,
        max_tokens: int = 4096,
    ) -> LLMResult[T]:
        model = model_for(self._settings, tier)
        trace_id = uuid.uuid4().hex  # also a valid OpenTelemetry trace id
        started = datetime.now(UTC)
        t0 = time.monotonic()
        resp = None
        parsed: T | None = None
        error: str | None = None
        try:
            # create() + our own validation (not messages.parse): usage and stop_reason are kept
            # even when the output is cut off or invalid, so every token is accounted for.
            resp = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": prompt.text, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": transform_schema(output)}},
            )
            parsed, error = _validate(resp, output)
        except anthropic.APIStatusError as e:
            error = f"Anthropic API error {e.status_code}"
            if e.status_code == 400 and "credit" in str(e).lower():
                error += " (credit balance too low)"
        except anthropic.APIConnectionError:
            error = "Anthropic API could not be reached"
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = _usage(resp)
        cost = cost_usd(model, usage)
        if cost is None:
            log.warning("no price for model %s; cost recorded as NULL", model)

        await self._record(tenant_id, prompt, model, usage, cost, latency_ms, error, trace_id)
        if self._tracer is not None:
            await self._tracer.send(
                TraceRecord(
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    agent=prompt.agent,
                    prompt_name=prompt.agent,
                    prompt_version=prompt.version,
                    prompt_ref=prompt.ref,
                    model=model,
                    input=user,
                    output=parsed.model_dump_json() if parsed is not None else None,
                    error=error,
                    usage=usage,
                    cost_usd=cost,
                    started=started,
                    ended=datetime.now(UTC),
                )
            )
        if error is not None or parsed is None:
            raise LLMError(error or "No output")
        return LLMResult(parsed, model, usage, cost, latency_ms, trace_id)

    async def _record(
        self,
        tenant_id: uuid.UUID | None,
        prompt: Prompt,
        model: str,
        usage: Usage,
        cost: Decimal | None,
        latency_ms: int,
        error: str | None,
        trace_id: str,
    ) -> None:
        """Own short transaction: a failed call is still recorded, whatever the caller does next."""
        if self._engine is None or tenant_id is None:
            return
        async with AsyncSession(self._engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            db.add(
                LlmCall(
                    tenant_id=tenant_id,
                    agent=prompt.agent,
                    prompt_ref=prompt.ref,
                    model=model,
                    status="error" if error else "ok",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    error=error,
                    trace_id=trace_id,
                )
            )
