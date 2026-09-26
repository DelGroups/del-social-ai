"""Copywriter: three distinct caption options per brief, Azerbaijani + Russian (docs/agent-team.md §3).

Tools: none (reads the brand profile and the brief it is given). Model tier: default (Sonnet).
It never writes prices, phone numbers or links; code adds contact details (agents.common).
Revisions rewrite only the options the Brand Guardian flagged.
"""
import json
import uuid

from pydantic import BaseModel, Field

from del_social.agents.common import Brief, brand_context, brief_block
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLM, LLMError, LLMResult, Tier, load_prompt

AGENT = "copywriter"


class CopyOption(BaseModel):
    angle: str = Field(description="One short English sentence: the idea that makes this option different")
    caption_az: str = Field(description="Azerbaijani (Latin script) caption body, including a call to action")
    caption_ru: str = Field(description="Russian caption body with the same meaning, natural Russian")
    hashtags: list[str] = Field(description="Hashtags, each starting with #, no spaces")
    alt_text: str = Field(description="Short Azerbaijani description of the photo for accessibility")


class CopyOutput(BaseModel):
    options: list[CopyOption] = Field(min_length=3, max_length=3, description="Exactly three options")
    question: str | None = Field(
        default=None,
        description="Only if the brief cannot be written without a human answer; otherwise null",
    )


class RevisedOptions(BaseModel):
    options: list[CopyOption] = Field(description="One rewritten option per option in <revision_request>, same order")


async def write_options(
    llm: LLM, tenant_id: uuid.UUID | None, profile: BrandProfile, brief: Brief
) -> LLMResult[CopyOutput]:
    user = "\n\n".join([brand_context(profile), brief_block(brief), "Write the three options now."])
    return await llm.structured(
        tenant_id=tenant_id,
        prompt=load_prompt(AGENT),
        user=user,
        output=CopyOutput,
        tier=Tier.DEFAULT,
        max_tokens=16000,  # a ceiling, not a cost: includes the model's thinking
    )


async def revise_options(
    llm: LLM,
    tenant_id: uuid.UUID | None,
    profile: BrandProfile,
    brief: Brief,
    kept: list[CopyOption],
    revision_request: str,
    count: int,
) -> LLMResult[RevisedOptions]:
    """Rewrite only the options the Brand Guardian flagged; the kept ones are context, not rewritten."""
    kept_block = (
        "<kept_options>\nAlready approved by the Brand Guardian. Do not rewrite them; keep your new options "
        "distinct from their angles.\n"
        + json.dumps([{"angle": o.angle, "caption_az": o.caption_az} for o in kept], ensure_ascii=False, indent=1)
        + "\n</kept_options>"
    )
    user = "\n\n".join([
        brand_context(profile),
        brief_block(brief),
        kept_block,
        revision_request,
        f"Rewrite exactly {count} option(s) now, in the order of the revision request.",
    ])
    result = await llm.structured(
        tenant_id=tenant_id,
        prompt=load_prompt(AGENT),
        user=user,
        output=RevisedOptions,
        tier=Tier.DEFAULT,
        max_tokens=16000,
    )
    if len(result.output.options) != count:
        raise LLMError(f"Expected {count} revised option(s), got {len(result.output.options)}")
    return result
