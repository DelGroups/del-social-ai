"""The YouTube Studio agents (ADR 012): output schemas and calls. Prompts live in agents/yt_*/.

None of them holds a tool: they read numbers computed by code and text that may come from other
people (comments, titles of other channels, web pages), which is data, never instructions
(CLAUDE.md principle 6). Every number, timestamp and credit is handled by code.

- yt_reporter (fast): the pulse every few hours and the daily report, from computed numbers.
- yt_reviewer (strategy): the deep channel review.
- yt_trends + yt_ideas (default): web research, then video ideas with evidence.
- yt_metadata (default): the publishing kit of one video.
- yt_thumbnail (default): thumbnail concepts; code renders them.
- yt_replies (fast): reply drafts for comments; sent only after the owner approves.
"""
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from del_social.llm import LLM, Effort, LLMResult, ResearchResult, Tier, load_prompt
from del_social.youtube.render import LAYOUTS, PALETTES

# --- reports ---


class Pulse(BaseModel):
    headline: str = Field(description="One line: the most useful thing to know now")
    summary: str = Field(description="2-4 sentences, numbers only as given in <facts>")
    highlights: list[str] = Field(description="0-4 short bullets, each quoting a number from <facts>")
    actions: list[str] = Field(description="0-3 concrete things the owner can do today")


async def report(llm: LLM, tenant_id: uuid.UUID, context: str) -> LLMResult[Pulse]:
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("yt_reporter"), user=context, output=Pulse,
                                tier=Tier.FAST, max_tokens=2000)


Area = Literal["packaging", "retention", "topics", "consistency", "audience", "shorts", "seo", "community", "growth"]


class ReviewArea(BaseModel):
    area: Area
    grade: Literal["strong", "ok", "weak", "unknown"] = Field(description="unknown when <facts> can't tell")
    finding: str = Field(description="1-3 sentences")
    evidence: str = Field(description="The numbers or videos from <facts> this rests on")
    advice: list[str] = Field(description="1-3 concrete steps")


class ReviewAction(BaseModel):
    title: str
    why: str
    how: str = Field(description="Exactly what to do, step by step, in 1-3 sentences")
    effort: Literal["low", "medium", "high"]
    impact: Literal["low", "medium", "high"]


class Review(BaseModel):
    headline: str = Field(description="The one-line verdict on the channel today")
    summary: str = Field(description="4-6 sentences")
    areas: list[ReviewArea] = Field(description="One entry per area that the facts say something about (4-9)")
    top_actions: list[ReviewAction] = Field(description="The 3-5 actions with the biggest effect, most important first")
    experiments: list[str] = Field(description="0-3 experiments to run in the next videos")
    questions: list[str] = Field(description="0-2 questions for the owner that would sharpen the next review")


async def review(llm: LLM, tenant_id: uuid.UUID, context: str, images: list[bytes] | None = None) -> LLMResult[Review]:
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("yt_reviewer"), user=context, output=Review,
                                tier=Tier.STRATEGY, effort=Effort.HIGH, max_tokens=12000, images=images or None)


# --- ideas ---


class Idea(BaseModel):
    title: str = Field(description="A working title in the channel's language")
    angle: str = Field(description="What the video shows or argues, 1-2 sentences")
    hook: str = Field(description="What happens in the first 10 seconds")
    format: Literal["long", "short", "series"]
    why: str = Field(description="Why this, why now")
    evidence: str = Field(description="[trend n], [competitor n] or [source n] references from the input")
    thumbnail: str = Field(description="The thumbnail idea in one sentence")
    keywords: list[str] = Field(description="2-6 search words people use")
    difficulty: Literal["easy", "medium", "hard"]


class Ideas(BaseModel):
    summary: str = Field(description="2-4 sentences on what is working in this field now")
    trends: list[str] = Field(description="0-5 observations, each with its reference")
    ideas: list[Idea] = Field(description="5-10 ideas, best first")


async def trend_notes(llm: LLM, tenant_id: uuid.UUID, request: str, max_searches: int = 5) -> ResearchResult:
    return await llm.research(tenant_id=tenant_id, prompt=load_prompt("yt_trends"), user=request, tier=Tier.DEFAULT,
                              max_searches=max_searches)


async def ideas(llm: LLM, tenant_id: uuid.UUID, context: str) -> LLMResult[Ideas]:
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("yt_ideas"), user=context, output=Ideas,
                                tier=Tier.DEFAULT, effort=Effort.MEDIUM, max_tokens=10000)


# --- publishing kit ---


class TitleOption(BaseModel):
    text: str = Field(description="At most 90 characters")
    style: Literal["search", "curiosity", "benefit", "emotional", "list"]
    why: str = Field(description="One sentence")


class ChapterPick(BaseModel):
    segment: int = Field(description="Index of the segment in <segments> where the chapter starts")
    title: str = Field(description="2-6 words")


class Translation(BaseModel):
    language: str = Field(description="Language code from <languages>, e.g. ru, en, tr")
    title: str
    description: str


class MetadataKit(BaseModel):
    titles: list[TitleOption] = Field(description="Exactly 3 different title options")
    description: str = Field(description="The description without chapters and hashtags (code adds them)")
    tags: list[str] = Field(description="10-25 tags, most important first, no # sign")
    hashtags: list[str] = Field(description="3-5 hashtags without the # sign")
    pinned_comment: str = Field(description="A comment to pin under the video that starts a conversation")
    chapters: list[ChapterPick] = Field(description="Empty when <segments> is empty or the video is short")
    translations: list[Translation] = Field(description="One per extra language in <languages>")
    thumbnail_texts: list[str] = Field(description="3 short thumbnail texts, at most 4 words each")


async def metadata(llm: LLM, tenant_id: uuid.UUID, context: str) -> LLMResult[MetadataKit]:
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("yt_metadata"), user=context, output=MetadataKit,
                                tier=Tier.DEFAULT, effort=Effort.MEDIUM, max_tokens=10000)


# --- thumbnails ---



class ThumbConcept(BaseModel):
    text: str = Field(description="At most 4 words, in the video's language")
    emphasis: str = Field(description="One word of the text to highlight, or empty")
    layout: Literal[LAYOUTS]  # type: ignore[valid-type]
    palette: Literal[PALETTES]  # type: ignore[valid-type]
    background_prompt: str = Field(description="English prompt for a text-free background image")
    why: str = Field(description="One sentence")


class ThumbConcepts(BaseModel):
    concepts: list[ThumbConcept] = Field(description="Exactly 3 clearly different concepts")


async def thumbnail_concepts(llm: LLM, tenant_id: uuid.UUID, context: str, images: list[bytes] | None = None) -> LLMResult[ThumbConcepts]:
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("yt_thumbnail"), user=context, output=ThumbConcepts,
                                tier=Tier.DEFAULT, max_tokens=3000, images=images or None)


# --- comments ---


class ReplyDraft(BaseModel):
    index: int = Field(description="The comment's index in <comments>")
    reply: str = Field(description="The reply, in the commenter's language; empty when skip is true")
    skip: bool = Field(description="True for spam, abuse or comments that need no answer")


class Replies(BaseModel):
    replies: list[ReplyDraft]


async def replies(llm: LLM, tenant_id: uuid.UUID, context: str) -> LLMResult[Replies]:
    return await llm.structured(tenant_id=tenant_id, prompt=load_prompt("yt_replies"), user=context, output=Replies,
                                tier=Tier.FAST, max_tokens=4000)
