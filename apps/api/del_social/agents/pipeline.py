"""Copywriter → Brand Guardian → (fix loop, max 2) for one brief (docs/phase-1-plan.md §5).

Revisions are selective: options the Guardian passed are kept as they are; only the
flagged ones are rewritten and re-reviewed. Step 5 wraps this in the LangGraph workflow
with the approval pause; the logic stays here. The result is plain JSON so it can be
stored (eval_items now, content_options later).
"""
import uuid
from decimal import Decimal

from del_social.agents import brand_guardian, copywriter
from del_social.agents.brand_guardian import OptionVerdict
from del_social.agents.common import Brief, assemble_caption
from del_social.agents.copywriter import CopyOption
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLM

MAX_REVISIONS = 2


def _snapshot(profile: BrandProfile, options: list[CopyOption], verdicts: list[OptionVerdict], revised: set[int]) -> list[dict]:
    return [
        {
            **o.model_dump(),
            "caption": assemble_caption(profile, o.caption_az, o.caption_ru, o.hashtags),
            "verdict": v.verdict,
            "findings": v.findings,
            "revised": i in revised,
        }
        for i, (o, v) in enumerate(zip(options, verdicts))
    ]


async def generate_for_brief(
    llm: LLM, tenant_id: uuid.UUID | None, profile: BrandProfile, brief: Brief, max_revisions: int = MAX_REVISIONS
) -> dict:
    cost = Decimal(0)
    written = await copywriter.write_options(llm, tenant_id, profile, brief)
    options = list(written.output.options)
    question = written.output.question
    verdicts, reviewed = await brand_guardian.review(llm, tenant_id, profile, brief, options)
    cost += (written.cost_usd or 0) + (reviewed.cost_usd or 0)
    attempts = [{"options": _snapshot(profile, options, verdicts, set()), "rewritten": [0, 1, 2]}]

    for _ in range(max_revisions):
        flagged = [i for i, v in enumerate(verdicts) if v.verdict != "pass"]
        if not flagged:
            break
        kept = [o for i, o in enumerate(options) if i not in flagged]
        request = brand_guardian.revision_request([(options[i], verdicts[i]) for i in flagged])
        revised = await copywriter.revise_options(llm, tenant_id, profile, brief, kept, request, len(flagged))
        new_verdicts, re_reviewed = await brand_guardian.review(
            llm, tenant_id, profile, brief, revised.output.options
        )
        cost += (revised.cost_usd or 0) + (re_reviewed.cost_usd or 0)
        for slot, option, verdict in zip(flagged, revised.output.options, new_verdicts):
            options[slot], verdicts[slot] = option, verdict
        attempts.append({"options": _snapshot(profile, options, verdicts, set(flagged)), "rewritten": flagged})

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
