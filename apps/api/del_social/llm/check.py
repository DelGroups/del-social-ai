"""One tiny real call per model tier to verify the Anthropic key and Langfuse tracing.

    docker compose exec api python -m del_social.llm.check [--tier fast|default|strategy]

Costs a fraction of a cent per tier. Not recorded in llm_calls (no tenant); it does
appear in Langfuse tagged "platform".
"""
import argparse
import asyncio
import sys

import httpx
from pydantic import BaseModel, Field

from del_social.core.config import get_settings
from del_social.llm import LLMError, Tier, build_llm, load_prompt


class Greeting(BaseModel):
    ok: bool
    azerbaijani: str = Field(description="'Salam' style greeting in Azerbaijani, max 5 words")
    russian: str = Field(description="Greeting in Russian, max 5 words")


async def main(tiers: list[Tier]) -> int:
    settings = get_settings()
    async with httpx.AsyncClient() as http:
        llm = build_llm(settings, engine=None, http=http)
        prompt = load_prompt("system_check")
        failed = 0
        for tier in tiers:
            try:
                r = await llm.structured(
                    tenant_id=None,
                    prompt=prompt,
                    user="Confirm you work and greet a furniture shop's customers.",
                    output=Greeting,
                    tier=tier,
                    max_tokens=200,
                )
                print(
                    f"{tier:8} {r.model:28} ok={r.output.ok} az={r.output.azerbaijani!r} ru={r.output.russian!r} "
                    f"tokens={r.usage.input_tokens}+{r.usage.output_tokens} cost=${r.cost_usd} {r.latency_ms}ms"
                )
            except LLMError as e:
                failed += 1
                print(f"{tier:8} FAILED: {e}")
        print("langfuse:", "configured" if settings.langfuse_configured else "NOT configured")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=[t.value for t in Tier], action="append")
    args = parser.parse_args()
    sys.exit(asyncio.run(main([Tier(t) for t in (args.tier or [Tier.FAST.value])])))
