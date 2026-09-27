"""The team meeting: the Team Lead asks each member, weighs the answers and brings the owner goals,
a week plan and improvements. Code measures metrics and checks every target, id and date; the
owner accepts goals and the plan from the chat. The LLM is a fake (ADR 009)."""
import json
import re
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from del_social.agents.team_lead import Action, LeadOutput
from del_social.agents.team_meeting import Agenda, GoalProposal, Improvement, Opinion, Outcome, PlanItem, Proposal, Question
from del_social.llm import LLMResult
from del_social.llm.pricing import Usage
from del_social.team import daily, lead, metrics, timing

from .conftest import O
from .test_agents import GOOD, FakeLLM
from .test_posts import product_with_photos, world  # noqa: F401  (fixture)


class FakeMeeting(FakeLLM):
    def __init__(self):
        super().__init__([[GOOD, GOOD, GOOD]])
        self.seen: dict[str, str] = {}
        self.lead: list[LeadOutput] = []

    async def structured(self, *, tenant_id, prompt, user, output, tier, max_tokens, effort=None, images=None):
        found = re.search(r'"product_id": "([0-9a-f-]+)"', user)
        if output in (Agenda, Opinion, Outcome) and found is None:
            from del_social.llm import LLMError
            raise LLMError("no products in this company")
        if output is Agenda:
            self.seen["agenda"] = user
            out = Agenda(focus="Engagement is low; how do we raise it?", questions=[
                Question(to="market_researcher", question="What do customers engage with?"),
                Question(to="copywriter", question="Which formats should we try?"),
                Question(to="brand_guardian", question="What hurts quality now?"),
            ])
        elif output is Opinion:
            role = re.search(r"<role>\nYou are the ([A-Za-z ]+)\.", user).group(1)
            self.seen[role] = user
            out = Opinion(answer=f"{role} answer", observations=[], risks=[], needs_from_owner=[],
                          proposals=[Proposal(title="Carousels", why="more saves", expected_effect="+ER", effort="low")])
        elif output is Outcome:
            self.seen["decision"] = user
            pid = found.group(1)
            out = Outcome(
                summary="We focus on engagement.", decisions=["Two carousels a week"], questions=[],
                goals=[
                    GoalProposal(title="ER 2% → 3%", metric="engagement_rate", target=3.0, weeks=4, why="market average"),
                    GoalProposal(title="Likes down?", metric="avg_likes", target=5, weeks=4, why="-"),  # worse than now: dropped
                    GoalProposal(title="Posts 0 → 5", metric="posts_per_week", target=5, weeks=2, why="consistency"),
                ],
                week_plan=[
                    PlanItem(day_offset=2, product_id=pid, format="carousel", angle="white finish", why="demand"),
                    PlanItem(day_offset=4, product_id=str(uuid.uuid4()), format="reel", angle="idea", why="-"),
                ],
                improvements=[Improvement(area="photos", title="Room photos", why="context sells", owner_action=True)],
            )
        elif output is LeadOutput:
            out = self.lead.pop(0)
        else:
            return await super().structured(tenant_id=tenant_id, prompt=prompt, user=user, output=output, tier=tier, max_tokens=max_tokens, effort=effort)
        return LLMResult(out, "fake", Usage(10, 5), Decimal("0.02"), 1, uuid.uuid4().hex)


@pytest.fixture
def meet(world):  # noqa: F811
    from del_social.main import app
    from del_social.routes.media import get_analyst

    fake = FakeMeeting()
    app.dependency_overrides[get_analyst] = lambda: fake
    return fake


async def seed_research(admin, tenant_id):
    """A finished market research with our Instagram numbers (as the daily research stores them)."""
    own = {"username": "del_furniture", "followers": 1000,
           "stats": {"engagement_rate_percent": 2.0, "avg_likes": 18.0, "avg_comments": 2.0, "posts_last_7_days": 1}}
    await admin.execute(
        "INSERT INTO daily_reports (tenant_id, kind, day, status, input, output, finished_at) VALUES "
        "($1, 'market', current_date, 'done', $2::jsonb, $3::jsonb, now())",
        tenant_id, json.dumps({"own": own}), json.dumps({"headline": "Ağ qarderoblar önə çıxır"}),
    )


async def test_meeting_goals_and_week_plan(client, meet, world, admin, app_engine, tenants, session_for):  # noqa: F811
    owner = await session_for(tenants["a_owner"])
    viewer = await session_for(tenants["a_viewer"])
    await seed_research(admin, tenants["a"])
    product_id, _ = await product_with_photos(client, tenants["a"], owner, n=1)

    # The owner asks something strategic: the Team Lead calls a meeting
    meet.lead.append(LeadOutput(reply="İclas çağırıram.", actions=[Action(type="team_meeting")]))
    r = await client.post(f"/tenants/{tenants['a']}/team/chat", json={"text": "Necə böyüyək?"}, headers={**owner, **O})
    assert r.status_code == 202
    await lead.settle()

    # Everyone got the same pack, measured by code; each member got its own question
    assert '"engagement_rate": {\n  "value": 2.0' in meet.seen["agenda"]
    assert "Which formats should we try?" in meet.seen["Copywriter and content strategist"]
    assert "What hurts quality now?" in meet.seen["Brand Guardian"]
    assert "Market Researcher answer" in meet.seen["decision"] and "<focus>" in meet.seen["decision"]

    live = (await client.get(f"/tenants/{tenants['a']}/team/live", headers=owner)).json()
    flow = next(j for j in live["jobs"] if j["kind"] == "meeting")
    assert [s["key"] for s in flow["steps"]] == ["agenda", "ask_market", "ask_content", "ask_quality", "decide", "deliver"]
    assert all(s["status"] == "done" for s in flow["steps"])

    msgs = (await client.get(f"/tenants/{tenants['a']}/team/chat", headers=owner)).json()
    card = next(m for m in msgs if (m["payload"] or {}).get("type") == "meeting")["payload"]
    assert [t["agent"] for t in card["transcript"]] == ["market_researcher", "copywriter", "brand_guardian"]
    goals = {g["metric"]: g for g in card["goals"]}
    assert set(goals) == {"engagement_rate", "posts_per_week"}  # the target below today's value was dropped by code
    assert goals["engagement_rate"]["baseline"] == 2.0 and goals["engagement_rate"]["status"] == "proposed"
    plan = card["week_plan"]
    assert plan[0]["status"] == "open" and plan[0]["product_id"] == product_id and plan[1]["status"] == "idea"
    assert card["improvements"][0]["owner_action"] is True

    # The owner decides: accept one goal, decline the other
    gid = goals["engagement_rate"]["goal_id"]
    assert (await client.post(f"/tenants/{tenants['a']}/goals/{gid}/decision", json={"accept": True}, headers={**viewer, **O})).status_code == 403
    ok = await client.post(f"/tenants/{tenants['a']}/goals/{gid}/decision", json={"accept": True}, headers={**owner, **O})
    assert ok.json()["status"] == "active"
    await client.post(f"/tenants/{tenants['a']}/goals/{goals['posts_per_week']['goal_id']}/decision", json={"accept": False}, headers={**owner, **O})
    assert (await client.post(f"/tenants/{tenants['a']}/goals/{gid}/decision", json={"accept": False}, headers={**owner, **O})).status_code == 409
    listed = (await client.get(f"/tenants/{tenants['a']}/goals", headers=viewer)).json()
    assert [g["status"] for g in listed] == ["active"]

    # The plan: one click prepares the startable posts for their days; each still waits for approval
    msg_id = next(m for m in msgs if (m["payload"] or {}).get("type") == "meeting")["message_id"]
    r = await client.post(f"/tenants/{tenants['a']}/team/messages/{msg_id}/plan/accept", headers={**owner, **O})
    assert r.status_code == 202 and r.json()["started"] == 1
    await lead.settle()
    post = next(p for p in (await client.get(f"/tenants/{tenants['a']}/posts", headers=owner)).json())
    when = datetime.fromisoformat(post["scheduled_at"]).astimezone(timing.BAKU)
    assert post["status"] == "ready" and when.time() == time(19, 0)
    assert when.date() == (datetime.now(UTC).astimezone(timing.BAKU) + timedelta(days=2)).date()
    again = await client.post(f"/tenants/{tenants['a']}/team/messages/{msg_id}/plan/accept", headers={**owner, **O})
    assert again.json()["started"] == 0

    # Goals are measured by code every day: reaching the target marks it achieved
    await admin.execute("UPDATE daily_reports SET input = jsonb_set(input, '{own,stats,engagement_rate_percent}', '3.4') WHERE tenant_id = $1", tenants["a"])
    changed = await metrics.update_goals(app_engine, tenants["a"], datetime.now(UTC).date())
    assert changed == [{"title": "ER 2% → 3%", "status": "achieved"}]

    # Another company sees none of it
    owner_b = await session_for(tenants["b_owner"])
    assert (await client.get(f"/tenants/{tenants['b']}/goals", headers=owner_b)).json() == []
    assert (await client.post(f"/tenants/{tenants['b']}/goals/{gid}/decision", json={"accept": True}, headers={**owner_b, **O})).status_code == 404


async def test_meeting_every_friday(client, meet, world, admin, app_engine, tenants, session_for):  # noqa: F811
    owner = await session_for(tenants["a_owner"])
    await product_with_photos(client, tenants["a"], owner, n=1)
    await seed_research(admin, tenants["a"])  # today's research is done, so only the report and meeting remain
    kw = {"engine": app_engine, "http": None, "llm": meet, "meta": None, "vault": None}
    today = datetime.now(timing.BAKU).date()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)
    thursday = friday - timedelta(days=1)
    await admin.execute("UPDATE daily_reports SET day = $2 WHERE tenant_id = $1", tenants["a"], friday)
    ran = await daily.tick(**kw, now=datetime.combine(friday, time(9, 40), timing.BAKU))
    assert (tenants["a"], "meeting") in ran
    assert (tenants["a"], "meeting") not in await daily.tick(**kw, now=datetime.combine(friday, time(10, 0), timing.BAKU))
    await admin.execute("UPDATE daily_reports SET day = $2 WHERE tenant_id = $1 AND kind = 'market'", tenants["a"], thursday)
    ran = await daily.tick(**kw, now=datetime.combine(thursday, time(9, 40), timing.BAKU))
    assert (tenants["a"], "meeting") not in ran
