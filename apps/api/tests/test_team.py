"""Team Room: the Team Lead turns a chat instruction into work; the wizard pauses for approval;
revisions by instruction; scheduled publishing; the live view. LLM and Meta are fakes.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from del_social.agents.team_lead import Action, LeadOutput
from del_social.llm import LLMError
from del_social.team import lead, scheduler, timing

from .conftest import O
from .test_agents import GOOD, FakeLLM
from .test_posts import IG_ID, PAGE_ID, connect, product_with_photos, world  # noqa: F401  (fixture)


# --- publish times are computed by code ---


def test_times_are_resolved_in_baku():
    at = lambda h: datetime(2026, 9, 27, h, 0, tzinfo=timing.BAKU)  # noqa: E731
    assert timing.resolve("after_approval") is None
    assert timing.resolve("today_evening", now=at(12)).astimezone(timing.BAKU) == datetime(2026, 9, 27, 19, 0, tzinfo=timing.BAKU)
    assert timing.resolve("today_evening", now=at(20)).astimezone(timing.BAKU).day == 28  # passed: next evening
    assert timing.resolve("tomorrow_morning", now=at(12)).astimezone(timing.BAKU) == datetime(2026, 9, 28, 10, 0, tzinfo=timing.BAKU)
    assert timing.resolve("specific", "2026-10-01", "18:30", now=at(12)).astimezone(timing.BAKU).hour == 18
    for bad in [("2026-09-26", "10:00"), ("2027-06-01", "10:00"), ("tomorrow", "x")]:
        with pytest.raises(timing.TimingError):
            timing.resolve("specific", *bad, now=at(12))


# --- the Team Lead ---


class FakeTeam(FakeLLM):
    """Scripted Team Lead + the scripted Copywriter/Guardian from test_agents."""

    def __init__(self):
        super().__init__([[GOOD, GOOD, GOOD], [GOOD]])
        self.lead: list[LeadOutput | Exception] = []
        self.lead_inputs: list[str] = []

    async def structured(self, **kw):
        if kw["prompt"].agent == "team_lead":
            self.lead_inputs.append(kw["user"])
            nxt = self.lead.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            from decimal import Decimal

            from del_social.llm import LLMResult
            from del_social.llm.pricing import Usage

            return LLMResult(nxt(kw["user"]) if callable(nxt) else nxt, "fake", Usage(), Decimal("0.01"), 1, uuid.uuid4().hex)
        return await super().structured(**kw)


@pytest.fixture
def team(world):  # noqa: F811
    from del_social.main import app
    from del_social.routes.media import get_analyst

    fake = FakeTeam()
    app.dependency_overrides[get_analyst] = lambda: fake
    return fake


def turl(tenant_id, path=""):
    return f"/tenants/{tenant_id}/team{path}"


def product_of(user: str) -> str:
    import re

    return re.search(r'"product_id": "([0-9a-f-]+)"', user).group(1)


async def say(client, tenant_id, headers, text):
    r = await client.post(turl(tenant_id, "/chat"), json={"text": text}, headers={**headers, **O})
    assert r.status_code == 202, r.text
    await lead.settle()


async def test_one_instruction_to_scheduled_post(client, team, world, admin, app_engine, tenants, session_for):  # noqa: F811
    owner = await session_for(tenants["a_owner"])
    await connect(admin, world.vault, tenants["a"], "instagram", IG_ID)
    await connect(admin, world.vault, tenants["a"], "facebook", PAGE_ID)
    await product_with_photos(client, tenants["a"], owner, n=2)
    team.lead.append(lambda user: LeadOutput(
        reply="Anladım, sabah axşam üçün karusel hazırlayıram.",
        actions=[Action(type="create_post", product_id=product_of(user), when="tomorrow_evening",
                        notes="Mention free measurement")],
    ))
    await say(client, tenants["a"], owner, "Wendy üçün sabah axşam post hazırla, pulsuz ölçünü qeyd et")
    assert "Wendy qarderobu" in team.lead_inputs[0] and "publishable_photos" in team.lead_inputs[0]

    msgs = (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()
    assert [m["role"] for m in msgs][:2] == ["user", "agent"]
    card = next(m for m in msgs if m["post"])
    post = card["post"]
    assert post["status"] == "ready" and post["scheduled_at"]
    assert card["task"]["steps"][3] == {"key": "approval", "agent": None, "status": "waiting"}
    assert card["task"]["status"] == "waiting_approval"
    when = datetime.fromisoformat(post["scheduled_at"]).astimezone(timing.BAKU)
    assert when.hour == 19 and when.date() == (datetime.now(UTC).astimezone(timing.BAKU) + timedelta(days=1)).date()

    live = (await client.get(turl(tenants["a"], "/live"), headers=owner)).json()
    assert [p["post_id"] for p in live["waiting"]] == [post["post_id"]]
    job = next(j for j in live["jobs"] if j["post_id"] == post["post_id"])
    assert job["status"] == "waiting_approval" and job["thumb_url"] and job["post_status"] == "ready"
    copy = next(a for a in live["agents"] if a["agent"] == "copywriter")
    assert copy["state"] == "idle" and copy["done_today"] >= 1
    assert any(e["agent"] == "brand_guardian" and e["kind"] == "finished" for e in live["events"])

    # A correction in words: the Copywriter rewrites, the Guardian re-checks, it comes back for approval
    r = await client.post(f"/tenants/{tenants['a']}/posts/{post['post_id']}/revise",
                          json={"instruction": "Qulpları var, qulpsuz yazma"}, headers={**owner, **O})
    assert r.status_code == 202
    msgs = (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()
    assert msgs[-1]["agent"] == "copywriter" and "Qulpları var" in msgs[-1]["text"]
    revise_prompt = [u for a, u in team.users if a == "copywriter"][-1]
    assert "The approver asks: Qulpları var, qulpsuz yazma" in revise_prompt

    approved = await client.post(f"/tenants/{tenants['a']}/posts/{post['post_id']}/approve", json={"confirm": True}, headers={**owner, **O})
    assert approved.json()["status"] == "scheduled"
    assert world.published("media_publish") == 0  # not yet: it waits for its time
    live = (await client.get(turl(tenants["a"], "/live"), headers=owner)).json()
    assert [p["post_id"] for p in live["scheduled"]] == [post["post_id"]] and live["waiting"] == []

    # Time comes: the scheduler (as the restricted app role, across tenants) publishes it once
    await admin.execute("UPDATE posts SET scheduled_at = now() - interval '1 minute' WHERE post_id = $1", uuid.UUID(post["post_id"]))
    from del_social.core.config import get_settings
    from del_social.core.deps import get_meta_optional, get_vault_optional
    from del_social.main import app

    meta, vault = app.dependency_overrides[get_meta_optional](), app.dependency_overrides[get_vault_optional]()
    assert await scheduler.publish_due(engine=app_engine, settings=get_settings(), meta=meta, vault=vault, poll=0) == 1
    assert await scheduler.publish_due(engine=app_engine, settings=get_settings(), meta=meta, vault=vault, poll=0) == 0
    assert world.published("media_publish") == 1
    done = (await client.get(f"/tenants/{tenants['a']}/posts/{post['post_id']}", headers=owner)).json()
    assert done["status"] == "published"
    msgs = (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()
    assert msgs[-1]["agent"] == "publisher" and "Paylaşıldı" in msgs[-1]["text"]
    assert msgs[-1]["task"]["status"] == "done"


async def test_lead_guards(client, team, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    viewer = await session_for(tenants["a_viewer"])
    owner_b = await session_for(tenants["b_owner"])
    await product_with_photos(client, tenants["a"], owner, n=1)

    # An id the lead made up is refused with a note, nothing starts
    team.lead.append(LeadOutput(reply="Hazırlayıram.", actions=[Action(type="create_post", product_id=str(uuid.uuid4()))]))
    await say(client, tenants["a"], owner, "post hazırla")
    msgs = (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()
    assert "Alınmadı: Product not found" in msgs[-1]["text"]
    assert (await client.get(f"/tenants/{tenants['a']}/posts", headers=owner)).json() == []

    # A viewer can talk but not start work
    team.lead.append(lambda user: LeadOutput(reply="Oldu.", actions=[Action(type="create_post", product_id=product_of(user))]))
    await say(client, tenants["a"], viewer, "post hazırla")
    msgs = (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()
    assert "rolunuz" in msgs[-1]["text"]
    assert (await client.get(f"/tenants/{tenants['a']}/posts", headers=owner)).json() == []

    # The model is down: the lead says so instead of going silent
    team.lead.append(LLMError("Anthropic API error 529"))
    await say(client, tenants["a"], owner, "status?")
    assert "cavab verə bilmirəm" in (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()[-1]["text"]

    # Asked about the market, the lead has the Market Researcher start now
    team.lead.append(LeadOutput(reply="Bazar analitiki indi araşdırır.", actions=[Action(type="run_market_research")]))
    await say(client, tenants["a"], owner, "Bazarı indi təhlil et")
    reports = (await client.get(f"/tenants/{tenants['a']}/daily?kind=market", headers=owner)).json()
    assert len(reports) == 1 and reports[0]["status"] in ("done", "failed")  # started by the lead, finished in the background
    assert "<latest_market_report>" in team.lead_inputs[-1]

    # Another company sees none of it
    assert (await client.get(turl(tenants["b"], "/chat"), headers=owner_b)).json() == []
    live_b = (await client.get(turl(tenants["b"], "/live"), headers=owner_b)).json()
    assert live_b["events"] == [] and live_b["waiting"] == [] and live_b["jobs"] == []


# --- the team speaks the owner's language ---


def test_language_is_detected_from_the_script():
    from del_social.team.texts import detect

    assert detect("Salam, Wendy üçün post hazırla") == "az"
    assert detect("salam necesen") == "az"
    assert detect("Подготовь пост на завтра") == "ru"
    assert detect("بازار را الان بررسی کن") == "fa"
    assert detect("Please prepare a post for tomorrow") == "en"
    assert detect("123 !!") is None


async def test_team_answers_in_the_owners_language(client, team, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    team.lead.append(LLMError("Anthropic API error 529"))
    await say(client, tenants["a"], owner, "بازار را بررسی کن")  # Persian
    msgs = (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()
    assert msgs[-1]["text"].startswith("الان نمی‌توانم پاسخ دهم")
    live = (await client.get(turl(tenants["a"], "/live"), headers=owner)).json()
    assert live["events"][0]["title"].startswith("نتوانست پاسخ دهد")

    # A fixed report language in the brand profile wins over the chat language
    await admin.execute(
        "INSERT INTO brand_profiles (tenant_id, version, data) VALUES ($1, 1, $2::jsonb)",
        tenants["a"], '{"market": {"report_language": "en"}}',
    )
    team.lead.append(LLMError("Anthropic API error 529"))
    await say(client, tenants["a"], owner, "Привет")
    msgs = (await client.get(turl(tenants["a"], "/chat"), headers=owner)).json()
    assert msgs[-1]["text"].startswith("I can't answer right now")
