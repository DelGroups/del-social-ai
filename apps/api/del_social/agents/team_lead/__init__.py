"""Team Lead: understands the owner's instructions, answers, and chooses the team's next actions.

It never does the work itself and never touches anything directly: it returns a reply and
a short list of actions from a fixed menu. Code checks and executes each action (CLAUDE.md
principles 1, 2 and 4). Model tier: default (Sonnet).
"""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from del_social.llm import LLM, Effort, LLMResult, Tier, load_prompt

AGENT = "team_lead"


class Action(BaseModel):
    type: Literal["create_post", "revise_post", "analyze_photos", "run_market_research", "morning_report", "team_meeting"]
    product_id: str | None = Field(default=None, description="create_post: id from <products>")
    when: Literal["after_approval", "today_evening", "tomorrow_morning", "tomorrow_evening", "specific"] | None = Field(
        default=None, description="create_post: when to publish once approved"
    )
    day: str | None = Field(default=None, description="when=specific: YYYY-MM-DD (Baku)")
    time: str | None = Field(default=None, description="when=specific: HH:MM (Baku)")
    channels: list[Literal["instagram", "facebook"]] | None = Field(default=None, description="create_post: default both")
    format: Literal["feed", "square", "landscape"] | None = Field(default=None, description="create_post: omit = automatic")
    notes: str | None = Field(default=None, description="create_post: what the Copywriter should know, in English")
    post_id: str | None = Field(default=None, description="revise_post: id from <posts>")
    instruction: str | None = Field(default=None, description="revise_post: the change the owner wants, in English")


class LeadOutput(BaseModel):
    reply: str = Field(description="Your answer to the owner, in the language they wrote in; short and concrete")
    actions: list[Action] = Field(description="0-3 actions for the team; empty if you only answer or ask")


async def decide(llm: LLM, tenant_id: uuid.UUID, context: str) -> LLMResult[LeadOutput]:
    return await llm.structured(
        tenant_id=tenant_id,
        prompt=load_prompt(AGENT),
        user=context,
        output=LeadOutput,
        tier=Tier.DEFAULT,
        effort=Effort.MEDIUM,
        max_tokens=8000,
    )
