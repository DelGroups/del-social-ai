"""The Team Lead's morning report: what was done, what the market says, today's plan, suggestions.

Suggestions come from a fixed menu (a post with a real product, or nothing); code validates the
product id and, only when the owner presses "do it", starts the work (CLAUDE.md principles 1-2).
Model tier: default (Sonnet).
"""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from del_social.llm import LLM, Effort, LLMResult, Tier, load_prompt

AGENT = "daily_briefing"


class Suggestion(BaseModel):
    title: str = Field(description="One line, what to do")
    why: str = Field(description="One or two sentences with the reason")
    action: Literal["create_post", "none"] = Field(description="create_post: the team can prepare it when the owner agrees")
    product_id: str | None = Field(default=None, description="create_post: id from <products>")
    when: Literal["after_approval", "today_evening", "tomorrow_morning", "tomorrow_evening"] | None = Field(
        default=None, description="create_post: suggested publishing slot"
    )
    notes: str | None = Field(default=None, description="create_post: what the Copywriter should stress, in English")


class Briefing(BaseModel):
    greeting: str = Field(description="One short line")
    yesterday: str = Field(description="What the team did, from <facts> only; 1-3 sentences")
    market: str = Field(description="The 1-3 most useful points from the market report; empty if there is none")
    today_plan: list[str] = Field(description="1-5 things the team will do today")
    suggestions: list[Suggestion] = Field(description="0-4 suggestions for the owner")
    questions: list[str] = Field(description="0-2 questions for the owner")


async def write(llm: LLM, tenant_id: uuid.UUID, context: str) -> LLMResult[Briefing]:
    return await llm.structured(
        tenant_id=tenant_id,
        prompt=load_prompt(AGENT),
        user=context,
        output=Briefing,
        tier=Tier.DEFAULT,
        effort=Effort.MEDIUM,
        max_tokens=10000,
    )
