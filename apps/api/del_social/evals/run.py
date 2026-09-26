"""Run an agent eval suite for one tenant and store the results for review in the panel.

    docker compose exec -T api python -m del_social.evals.run \\
        --tenant <tenant_id> --suite copywriter [--limit N] [--only id1,id2] < evals/copywriter/briefs.yaml

Suites:
- copywriter: the full Copywriter → Brand Guardian pipeline per brief; humans rate each option.
- brand_guardian: known-bad (and known-good) captions; checks the Guardian's verdicts automatically.

Costs real money (roughly $0.03–0.10 per copywriter brief); run it deliberately.
"""
import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import brand_guardian
from del_social.agents.common import Brief
from del_social.agents.copywriter import CopyOption
from del_social.agents.pipeline import generate_for_brief
from del_social.core.config import get_settings
from del_social.core.db import make_engine, set_tenant
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLM, LLMError, build_llm, load_prompt
from del_social.models import BrandProfileVersion, EvalItem, EvalRun

CONCURRENCY = 4


async def _load_profile(engine: AsyncEngine, tenant_id: uuid.UUID) -> tuple[int, BrandProfile]:
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.scalar(select(BrandProfileVersion).order_by(BrandProfileVersion.version.desc()).limit(1))
        if row is None:
            raise SystemExit("This tenant has no saved brand profile yet")
        return row.version, BrandProfile.model_validate(row.data)


async def _run_case(llm: LLM, tenant_id: uuid.UUID, profile: BrandProfile, suite: str, case: dict) -> dict:
    if suite == "copywriter":
        brief = Brief.model_validate({k: v for k, v in case.items() if k != "review_hint"})
        return await generate_for_brief(llm, tenant_id, profile, brief)
    brief = Brief.model_validate(case["brief"])
    option = CopyOption(angle="eval case", alt_text="", **case["option"])
    verdicts, result = await brand_guardian.review(llm, tenant_id, profile, brief, [option])
    got = verdicts[0].verdict
    expected = case["expect"]
    return {
        "brief_id": case["id"],
        "expect": expected,
        "got": got,
        "correct": got == expected if expected == "pass" else got != "pass",
        "findings": verdicts[0].findings,
        "cost_usd": str(result.cost_usd or 0),
    }


async def run(tenant_id: uuid.UUID, suite: str, cases: list[dict]) -> uuid.UUID:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    version, profile = await _load_profile(engine, tenant_id)
    prompts = {a: load_prompt(a).ref for a in (["copywriter", "brand_guardian"] if suite == "copywriter" else ["brand_guardian"])}

    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        run_row = EvalRun(
            run_id=uuid.uuid4(), tenant_id=tenant_id, suite=suite, prompt_refs=prompts,
            brand_version=version, briefs_total=len(cases),
        )
        db.add(run_row)
        await db.flush()  # the run must exist before its items (no ORM relationship orders them)
        items = [
            EvalItem(item_id=uuid.uuid4(), run_id=run_row.run_id, tenant_id=tenant_id, position=i, brief=c)
            for i, c in enumerate(cases)
        ]
        db.add_all(items)
    print(f"run {run_row.run_id}: {len(cases)} cases, suite={suite}, brand v{version}, prompts={prompts}", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    total = Decimal(0)
    async with httpx.AsyncClient() as http:
        llm = build_llm(settings, engine, http)

        async def one(item: EvalItem, case: dict) -> None:
            nonlocal total
            async with sem:
                result, error = None, None
                try:
                    result = await _run_case(llm, tenant_id, profile, suite, case)
                    total += Decimal(result["cost_usd"])
                except (LLMError, ValueError) as e:
                    error = str(e)[:500]
                async with AsyncSession(engine) as db, db.begin():
                    await set_tenant(db, tenant_id)
                    await db.execute(
                        update(EvalItem).where(EvalItem.item_id == item.item_id).values(result=result, error=error)
                    )
                status = "ERROR " + error if error else (
                    f"passed {result['passed']}/3, revisions {result['revisions']}" if suite == "copywriter"
                    else f"expect {result['expect']}, got {result['got']}"
                )
                print(f"  [{item.position + 1}/{len(cases)}] {case.get('id')}: {status}", flush=True)

        await asyncio.gather(*(one(i, c) for i, c in zip(items, cases)))

    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        await db.execute(
            update(EvalRun).where(EvalRun.run_id == run_row.run_id)
            .values(status="done", cost_usd=total, finished_at=datetime.now(UTC))
        )
    await engine.dispose()
    print(f"done: cost ${total}", flush=True)
    return run_row.run_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True, type=uuid.UUID)
    parser.add_argument("--suite", required=True, choices=["copywriter", "brand_guardian"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only", help="comma-separated case ids")
    args = parser.parse_args()
    cases = yaml.safe_load(sys.stdin.read())
    if not isinstance(cases, list):
        raise SystemExit("stdin must be a YAML list of cases")
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.get("id") in wanted]
    if args.limit:
        cases = cases[: args.limit]
    asyncio.run(run(args.tenant, args.suite, cases))


if __name__ == "__main__":
    main()
