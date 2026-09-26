"""Copywriter: three distinct caption options per brief, Azerbaijani + Russian (docs/agent-team.md §3).

Tools: none (reads the brand profile and the brief it is given). Model tier: default (Sonnet).
It never writes prices, phone numbers or links; code adds contact details (agents.common).
"""
import uuid

from pydantic import BaseModel, Field

from del_social.agents.common import Brief, brand_context, brief_block
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLM, LLMResult, Tier, load_prompt

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


def _user_message(profile: BrandProfile, brief: Brief, revision: str | None) -> str:
    parts = [brand_context(profile), brief_block(brief)]
    if revision:
        parts.append(revision)
    parts.append("Write the three options now.")
    return "\n\n".join(parts)


async def write_options(
    llm: LLM,
    tenant_id: uuid.UUID | None,
    profile: BrandProfile,
    brief: Brief,
    revision: str | None = None,
) -> LLMResult[CopyOutput]:
    """revision: the Brand Guardian's findings on the previous attempt, as a <revision_request> block."""
    return await llm.structured(
        tenant_id=tenant_id,
        prompt=load_prompt(AGENT),
        user=_user_message(profile, brief, revision),
        output=CopyOutput,
        tier=Tier.DEFAULT,
        max_tokens=6000,
    )
