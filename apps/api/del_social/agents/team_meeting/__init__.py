"""The team meeting: the Team Lead orchestrates, the agents think, the owner decides (ADR 009).

Agents never talk to each other directly (CLAUDE.md principle 1). A meeting is:
1. agenda: the Team Lead reads the team's pack (numbers, goals, market, products) and asks each
   member one specific question;
2. members: the Market Researcher, the Copywriter and the Brand Guardian answer in parallel,
   each from its own role, with proposals;
3. decision: the Team Lead weighs the answers and proposes goals, a week plan, improvements and
   questions for the owner. Code validates every id and number; the owner accepts or declines.
"""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from del_social.llm import LLM, Effort, LLMResult, Tier, load_prompt

Member = Literal["market_researcher", "copywriter", "brand_guardian"]
MEMBERS: tuple[Member, ...] = ("market_researcher", "copywriter", "brand_guardian")
Metric = Literal["followers", "engagement_rate", "avg_likes", "avg_comments", "posts_per_week"]

ROLES: dict[str, str] = {
    "market_researcher": (
        "You are the Market Researcher. You study demand, competitors and customers every day. Answer from the "
        "market report, the competitor numbers and customer comments; say what the evidence shows and how strong it is."
    ),
    "copywriter": (
        "You are the Copywriter and content strategist. You write the posts in Azerbaijani and Russian. Think about "
        "angles, hooks, formats (single photo, carousel, reels, stories), series and what this audience engages with."
    ),
    "brand_guardian": (
        "You are the Brand Guardian. You protect quality and the brand: consistency, claims that must be true, "
        "photo quality, risks, what went wrong or could go wrong, and what the team must not do."
    ),
}


class Question(BaseModel):
    to: Member
    question: str = Field(description="One specific question for this member, tied to the focus")


class Agenda(BaseModel):
    focus: str = Field(description="The one thing this meeting must decide, one sentence")
    questions: list[Question] = Field(description="Exactly one question for each of the three members")


class Proposal(BaseModel):
    title: str
    why: str = Field(description="The evidence or reasoning, one or two sentences")
    expected_effect: str = Field(description="What should improve, measurably if possible")
    effort: Literal["low", "medium", "high"]


class Opinion(BaseModel):
    answer: str = Field(description="Direct answer to the Team Lead's question, 2-4 sentences")
    observations: list[str] = Field(description="0-3 facts you rely on, from the pack")
    proposals: list[Proposal] = Field(description="1-3 concrete proposals")
    risks: list[str] = Field(description="0-2 risks")
    needs_from_owner: list[str] = Field(description="0-2 things only the owner can provide")


class GoalProposal(BaseModel):
    title: str = Field(description="Short, e.g. 'Engagement 2% → 3%'")
    metric: Metric
    target: float = Field(description="Target value of the metric (same unit as <metrics>)")
    weeks: int = Field(description="Weeks to reach it, 2-12")
    why: str


class PlanItem(BaseModel):
    day_offset: int = Field(description="1 = tomorrow … 7")
    product_id: str | None = Field(description="id from <products> with publishable photos, or null for an idea only")
    format: Literal["photo", "carousel", "reel", "story"]
    angle: str = Field(description="What the post shows or says")
    why: str


class Improvement(BaseModel):
    area: Literal["content", "photos", "engagement", "research", "products", "process"]
    title: str
    why: str
    owner_action: bool = Field(description="True if the owner has to do something (photos, info, decision)")


class Outcome(BaseModel):
    summary: str = Field(description="What the team concluded, 3-5 sentences")
    decisions: list[str] = Field(description="1-4 decisions the team takes now")
    goals: list[GoalProposal] = Field(description="0-3 measurable goals to propose to the owner")
    week_plan: list[PlanItem] = Field(description="0-7 posts for the next 7 days")
    improvements: list[Improvement] = Field(description="1-5 things that must get better, beyond posting")
    questions: list[str] = Field(description="0-2 questions for the owner")


async def agenda(llm: LLM, tenant_id: uuid.UUID, pack: str) -> LLMResult[Agenda]:
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("meeting_agenda"), user=pack, output=Agenda,
                                tier=Tier.DEFAULT, effort=Effort.MEDIUM, max_tokens=6000)


async def opinion(llm: LLM, tenant_id: uuid.UUID, member: str, question: str, pack: str, language: str) -> LLMResult[Opinion]:
    user = "\n\n".join([
        f"<role>\n{ROLES[member]}\n</role>",
        f"<report_language>{language}</report_language>",
        f"<question_from_team_lead>\n{question}\n</question_from_team_lead>",
        pack,
    ])
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("meeting_member"), user=user, output=Opinion,
                                tier=Tier.DEFAULT, effort=Effort.MEDIUM, max_tokens=6000)


async def decide(llm: LLM, tenant_id: uuid.UUID, pack: str) -> LLMResult[Outcome]:
    # Weekly strategy is the Team Lead's most important decision: the strongest model (CLAUDE.md stack)
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("meeting_decision"), user=pack, output=Outcome,
                                tier=Tier.STRATEGY, effort=Effort.MEDIUM, max_tokens=16000)
