"""Copywriter → Brand Guardian → (fix loop, max 2) for one brief (docs/phase-1-plan.md §5).

Step 5 wraps this in the LangGraph workflow with the approval pause; the logic stays here.
The result is plain JSON so it can be stored (eval_items now, content_options later).
"""
import uuid
from decimal import Decimal

from del_social.agents import brand_guardian, copywriter
from del_social.agents.common import Brief, assemble_caption
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLM

MAX_REVISIONS = 2


async def generate_for_brief(
    llm: LLM, tenant_id: uuid.UUID | None, profile: BrandProfile, brief: Brief, max_revisions: int = MAX_REVISIONS
) -> dict:
    attempts: list[dict] = []
    cost = Decimal(0)
    revision: str | None = None
    question: str | None = None
    for attempt in range(max_revisions + 1):
        written = await copywriter.write_options(llm, tenant_id, profile, brief, revision)
        options = written.output.options
        question = written.output.question or question
        verdicts, reviewed = await brand_guardian.review(llm, tenant_id, profile, brief, options)
        cost += (written.cost_usd or 0) + (reviewed.cost_usd or 0)
        attempts.append({
            "options": [
                {
                    **o.model_dump(),
                    "caption": assemble_caption(profile, o.caption_az, o.caption_ru, o.hashtags),
                    "verdict": v.verdict,
                    "findings": v.findings,
                }
                for o, v in zip(options, verdicts)
            ],
            "traces": {"copywriter": written.trace_id, "brand_guardian": reviewed.trace_id},
        })
        if all(v.verdict == "pass" for v in verdicts) or attempt == max_revisions:
            break
        revision = brand_guardian.revision_request(options, verdicts)
    final = attempts[-1]["options"]
    return {
        "brief_id": brief.id,
        "options": final,
        "passed": sum(o["verdict"] == "pass" for o in final),
        "revisions": len(attempts) - 1,
        "question": question,
        "cost_usd": str(cost),
        "attempts": attempts,
    }
