"""Market Researcher: turns the day's collected data (competitors, our page, customer comments,
web notes, competitor photos) into a short report with evidence and post ideas.

Reads only; holds no tools (CLAUDE.md principle 6: it reads untrusted content). Numbers come
from code (del_social.research.collect). Model tier: default (Sonnet), with images.
"""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from del_social.llm import LLM, Effort, LLMResult, Tier, load_prompt

AGENT = "market_researcher"
WEB_AGENT = "web_researcher"

Confidence = Literal["low", "medium", "high"]


class Finding(BaseModel):
    title: str = Field(description="One line")
    detail: str = Field(description="1-3 sentences")
    evidence: str = Field(description="Where this comes from: account + date, a number from <facts>, a comment, or [source number]")
    confidence: Confidence


class PostIdea(BaseModel):
    product_id: str | None = Field(description="id from <products>, or null for a general post")
    product_name: str
    angle: str = Field(description="What the post shows or says")
    why: str = Field(description="Why this, why now; point to the evidence")
    format: Literal["photo", "carousel", "reel", "story"]


class MarketReport(BaseModel):
    headline: str = Field(description="The single most useful finding today, one line")
    summary: str = Field(description="3-5 sentences for the owner")
    demand: list[Finding] = Field(description="What customers want now: models, sizes, styles (0-4)")
    colors_materials: list[Finding] = Field(description="Colours, finishes and materials in demand (0-3)")
    competitors: list[Finding] = Field(description="What competitors post and what works for them (0-4)")
    customer_voice: list[Finding] = Field(description="What our own customers ask or say (0-3)")
    opportunities: list[Finding] = Field(description="Gaps or timing the company can use (0-3)")
    post_ideas: list[PostIdea] = Field(description="0-4 concrete post ideas with our products")
    questions: list[str] = Field(description="0-2 questions for the owner that would improve the research")
    data_gaps: list[str] = Field(description="What data was missing or unusable today")


async def web_notes(llm: LLM, tenant_id: uuid.UUID, request: str, max_searches: int = 5):
    return await llm.research(
        tenant_id=tenant_id, prompt=load_prompt(WEB_AGENT), user=request, tier=Tier.DEFAULT, max_searches=max_searches,
    )


async def analyse(llm: LLM, tenant_id: uuid.UUID, context: str, images: list[bytes]) -> LLMResult[MarketReport]:
    return await llm.structured(
        tenant_id=tenant_id,
        prompt=load_prompt(AGENT),
        user=context,
        output=MarketReport,
        tier=Tier.DEFAULT,
        effort=Effort.MEDIUM,
        max_tokens=16000,
        images=images or None,
    )
