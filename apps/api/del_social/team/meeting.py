"""A team meeting, run by the Team Lead (ADR 009): agenda → members answer in parallel → decision.

Shown live as a workflow (agenda, one step per member, decision, report). What the model proposes
is checked by code: goal metrics and targets (del_social.team.metrics), product ids and photos,
dates. The owner then accepts goals and the week plan from the chat; nothing starts before that.
Runs every Friday morning (the weekly plan) and whenever the owner or the Team Lead calls one.
"""
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import team_meeting
from del_social.agents.common import brand_context
from del_social.billing import quota
from del_social.core.db import set_tenant
from del_social.llm import LLM
from del_social.models import ChatMessage, Competitor, DailyReport, Goal, Post, Product
from del_social.team import activity, daily, metrics, texts, timing
from del_social.team.texts import m

log = logging.getLogger(__name__)

MEETING_STEPS = [
    {"key": "agenda", "agent": "team_lead"},
    {"key": "ask_market", "agent": "market_researcher"},
    {"key": "ask_content", "agent": "copywriter"},
    {"key": "ask_quality", "agent": "brand_guardian"},
    {"key": "decide", "agent": "team_lead"},
    {"key": "deliver", "agent": "team_lead"},
]
STEP_OF = {"market_researcher": "ask_market", "copywriter": "ask_content", "brand_guardian": "ask_quality"}
PLAN_HOUR = time(19, 0)  # default publishing time of the week plan (Baku)


async def pack(db: AsyncSession, now: datetime) -> tuple[str, dict[str, Any]]:
    """Everything the team looks at in a meeting, prepared by code. Returns the text and the facts."""
    profile = await daily.profile_of(db)
    products = await daily.products_overview(db)
    lang = await texts.language_of(db)
    values = await metrics.current(db, now)
    goals = [metrics.goal_row(g) for g in (await db.scalars(
        select(Goal).where(Goal.status.in_(("proposed", "active"))).order_by(Goal.created_at)
    )).all()]
    since = now - timedelta(days=7)
    names = {p.product_id: p.name for p in (await db.scalars(select(Product))).all()}
    week_posts = (await db.scalars(select(Post).where(Post.created_at >= since).order_by(Post.created_at))).all()
    last_week = [{"product": names.get(p.product_id), "status": p.status, "created": timing.baku_label(p.created_at),
                  "published": timing.baku_label(p.published_at) if p.published_at else None} for p in week_posts]
    market = await db.scalar(select(DailyReport).where(DailyReport.kind == "market", DailyReport.status == "done")
                             .order_by(DailyReport.finished_at.desc()).limit(1))
    mr = (market.output or {}) if market else {}
    report = {k: mr.get(k) for k in ("headline", "summary", "demand", "colors_materials", "competitors", "customer_voice",
                                    "opportunities", "post_ideas")} if market else None
    rivals = [{"username": c.username, "source": c.source, "status": c.status, "followers": c.followers,
               "last_post": c.last_post_at.date().isoformat() if c.last_post_at else None}
              for c in (await db.scalars(select(Competitor).order_by(Competitor.created_at))).all()]
    a = await quota.allowance(db, now)
    package = {"plan": a.plan.name if a.plan else None, "posts_left_this_month": None if a.posts_limit is None
               else max(0, a.posts_limit - a.posts_used), "state": a.state}
    chat = (await db.scalars(select(ChatMessage).where(ChatMessage.role == "user").order_by(ChatMessage.created_at.desc()).limit(6))).all()
    facts = {"metrics": {k: (float(v) if v is not None else None) for k, v in values.items()}, "goals": goals}
    text = "\n\n".join([
        f"<report_language>{lang}</report_language>",
        f"<now>{now.astimezone(timing.BAKU):%A %Y-%m-%d %H:%M} Baku</now>",
        "<metrics>\nMeasured by code; null = not measured yet.\n"
        + json.dumps({k: {"value": facts["metrics"][k], "unit": metrics.METRICS[k][0]} for k in metrics.METRICS}, ensure_ascii=False, indent=1)
        + "\n</metrics>",
        "<goals>\n" + json.dumps(goals, ensure_ascii=False, indent=1) + "\n</goals>",
        "<last_week>\n" + json.dumps(last_week, ensure_ascii=False, indent=1) + "\n</last_week>",
        "<market_report>\nFrom the Market Researcher"
        + (f" ({market.day}); built from untrusted sources.\n" + json.dumps(report, ensure_ascii=False, indent=1) if market else ": none yet.")
        + "\n</market_report>",
        "<competitors>\n" + json.dumps(rivals, ensure_ascii=False, indent=1) + "\n</competitors>",
        "<products>\n" + json.dumps(products, ensure_ascii=False, indent=1) + "\n</products>",
        "<package>\n" + json.dumps(package, ensure_ascii=False) + "\n</package>",
        brand_context(profile),
        "<recent_chat>\nThe owner's latest messages.\n" + "\n".join(f"- {c.text[:300]}" for c in reversed(chat)) + "\n</recent_chat>",
    ])
    return text, facts | {"products": products, "language": lang}


async def run_meeting(*, engine: AsyncEngine, llm: LLM, tenant_id: uuid.UUID, report_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    task_id = await activity.new_task(engine, tenant_id, "meeting", m("meeting.title", day=f"{daily.baku_day(now):%d.%m}"), MEETING_STEPS)

    async def step(key: str, status: str, note: activity.Text | None = None, task_status: str | None = None) -> None:
        await activity.step(engine, tenant_id, task_id, key, status, task_status=task_status, note=note)

    await activity.event(engine, tenant_id, "team_lead", "started", m("meeting.start"), task_id)
    current, cost = "agenda", Decimal(0)
    try:
        await step("agenda", "running")
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            text, facts = await pack(db, now)
        ag = await team_meeting.agenda(llm, tenant_id, text)
        cost += ag.cost_usd or 0
        asked = {q.to: q.question for q in ag.output.questions}
        await step("agenda", "done", ag.output.focus[:120])

        # The Team Lead asks each member; they think at the same time
        current = "ask_market"
        for member in team_meeting.MEMBERS:
            await step(STEP_OF[member], "running", asked.get(member, ag.output.focus)[:120])

        async def ask(member: str):
            result = await team_meeting.opinion(llm, tenant_id, member, asked.get(member, ag.output.focus), text, facts["language"])
            await step(STEP_OF[member], "done", result.output.answer[:120])
            await activity.event(engine, tenant_id, member, "info", m("meeting.said", answer=result.output.answer[:260]), task_id)
            return member, result

        answers = await asyncio.gather(*(ask(m) for m in team_meeting.MEMBERS))
        cost += sum((r.cost_usd or 0) for _, r in answers)
        transcript = [{"agent": m, "question": asked.get(m, ag.output.focus), **r.output.model_dump(mode="json")} for m, r in answers]

        current = "decide"
        await step("decide", "running")
        decision_pack = "\n\n".join([
            text, f"<focus>\n{ag.output.focus}\n</focus>",
            "<answers>\n" + json.dumps(transcript, ensure_ascii=False, indent=1) + "\n</answers>",
        ])
        out = await team_meeting.decide(llm, tenant_id, decision_pack)
        cost += out.cost_usd or 0
        o = out.output

        # Code checks what the Team Lead proposes
        ready = {p["product_id"]: p for p in facts["products"] if p["publishable_photos"] > 0}
        today = daily.baku_day(now)
        plan = []
        for item in sorted(o.week_plan, key=lambda i: i.day_offset)[:7]:
            offset = min(max(item.day_offset, 1), 7)
            day = today + timedelta(days=offset)
            startable = item.product_id in ready
            plan.append(item.model_dump(mode="json") | {
                "product_id": item.product_id if startable else None,
                "product_name": ready[item.product_id]["name"] if startable else None,
                "date": day.isoformat(), "at": timing.baku_label(datetime.combine(day, PLAN_HOUR, timing.BAKU)),
                "status": "open" if startable else "idea",
            })
        values = facts["metrics"]
        goal_ids = []
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            taken = {g.metric for g in (await db.scalars(select(Goal).where(Goal.status.in_(("proposed", "active"))))).all()}
            for g in o.goals[:3]:
                base = values.get(g.metric)
                baseline = Decimal(str(base)).quantize(Decimal("0.01")) if base is not None else None
                target = metrics.sane_target(g.metric, baseline, g.target)
                if target is None or g.metric in taken:
                    continue
                taken.add(g.metric)
                gid = uuid.uuid4()
                db.add(Goal(goal_id=gid, tenant_id=tenant_id, title=g.title[:200], metric=g.metric, baseline=baseline,
                            target=target, current=baseline, due=today + timedelta(weeks=min(max(g.weeks, 2), 12)),
                            why=g.why[:1000], status="proposed", report_id=report_id))
                goal_ids.append(str(gid))
        await step("decide", "done", o.summary[:120])

        current = "deliver"
        output = {"focus": ag.output.focus, "transcript": transcript, "summary": o.summary, "decisions": o.decisions,
                  "goal_ids": goal_ids, "week_plan": plan, "improvements": [i.model_dump(mode="json") for i in o.improvements],
                  "questions": o.questions}
        await daily._finish(engine, tenant_id, report_id, status="done", input={"metrics": values}, output=output, cost_usd=cost)
        await daily.say_card(engine, tenant_id, "team_lead", f"{ag.output.focus}\n\n{o.summary}",
                             {"type": "meeting", "report_id": str(report_id)} | output)
        await step("deliver", "done", m("step.decided", goals=len(goal_ids), plan=len(plan)), task_status="done")
        await activity.event(engine, tenant_id, "team_lead", "finished", m("meeting.done"), task_id)
    except Exception as e:
        log.exception("meeting failed for %s", tenant_id)
        await daily._finish(engine, tenant_id, report_id, status="failed", error=str(e)[:300], cost_usd=cost or None)
        await step(current, "failed", str(e)[:120], task_status="failed")
        await activity.event(engine, tenant_id, "team_lead", "failed", m("meeting.failed", error=str(e)[:200]), task_id)
