"""Eval runs of one tenant: browse results, rate each option (docs/phase-1-plan.md §10).

A copywriter brief counts as a success when at least one of its options is rated
"publishable" (as is, without edits). Phase 1 target: ≥ 80% of rated briefs.
"""
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.models import EvalItem, EvalRun
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/evals", tags=["evals"])

can_view = require_permission(Permission.VIEW)
can_rate = require_permission(Permission.APPROVE_CONTENT)

Rating = Literal["publishable", "needs_edit", "wrong"]
TARGET = 0.8


class RunSummary(BaseModel):
    run_id: uuid.UUID
    suite: str
    status: str
    brand_version: int
    prompt_refs: dict[str, str]
    briefs_total: int
    completed: int
    failed: int
    rated: int
    successes: int  # copywriter: briefs with ≥1 publishable option; guardian: correct verdicts
    success_rate: float | None
    target: float
    cost_usd: Decimal
    created_at: datetime
    finished_at: datetime | None


class ItemOut(BaseModel):
    item_id: uuid.UUID
    position: int
    brief: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    ratings: dict[str, Rating]
    note: str | None
    rated_at: datetime | None


class RunDetail(RunSummary):
    items: list[ItemOut]


class RatingIn(BaseModel):
    ratings: dict[Literal["0", "1", "2"], Rating]
    note: str | None = Field(default=None, max_length=2000)


def _summary(run: EvalRun, items: list[EvalItem]) -> dict:
    completed = [i for i in items if i.result is not None]
    if run.suite == "brand_guardian":
        rated = len(completed)
        successes = sum(bool(i.result.get("correct")) for i in completed)
    else:
        rated_items = [i for i in items if i.ratings]
        rated = len(rated_items)
        successes = sum("publishable" in i.ratings.values() for i in rated_items)
    return {
        "run_id": run.run_id,
        "suite": run.suite,
        "status": run.status,
        "brand_version": run.brand_version,
        "prompt_refs": run.prompt_refs,
        "briefs_total": run.briefs_total,
        "completed": len(completed),
        "failed": sum(i.error is not None for i in items),
        "rated": rated,
        "successes": successes,
        "success_rate": round(successes / rated, 3) if rated else None,
        "target": TARGET,
        "cost_usd": run.cost_usd,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


async def _items(db: AsyncSession, run_id: uuid.UUID) -> list[EvalItem]:
    return list((await db.scalars(select(EvalItem).where(EvalItem.run_id == run_id).order_by(EvalItem.position))).all())


@router.get("", response_model=list[RunSummary])
async def list_runs(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[RunSummary]:
    runs = (await db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()))).all()
    return [RunSummary(**_summary(r, await _items(db, r.run_id))) for r in runs]


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)
) -> RunDetail:
    run = await db.get(EvalRun, run_id)  # RLS: this tenant only
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eval run not found")
    items = await _items(db, run_id)
    return RunDetail(
        **_summary(run, items),
        items=[ItemOut.model_validate(i, from_attributes=True) for i in items],
    )


@router.put("/{run_id}/items/{item_id}", response_model=ItemOut)
async def rate_item(
    run_id: uuid.UUID,
    item_id: uuid.UUID,
    body: RatingIn,
    ctx: TenantContext = Depends(can_rate),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    item = await db.get(EvalItem, item_id)
    if item is None or item.run_id != run_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    if item.result is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This brief has no result to rate")
    item.ratings = dict(body.ratings)
    item.note = body.note
    item.rated_by = ctx.account.account_id
    item.rated_at = datetime.now(UTC)
    await db.flush()
    return ItemOut.model_validate(item, from_attributes=True)
