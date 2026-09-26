"""Copywriter + Brand Guardian: deterministic checks, caption assembly, fix loop, eval runs.

The LLM is replaced by a scripted fake: these tests never call Anthropic.
"""
import json
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from del_social.agents import brand_guardian
from del_social.agents.brand_guardian import GuardianOutput, OptionReview
from del_social.agents.brand_guardian.checks import az_lower
from del_social.agents.common import Brief, assemble_caption, brand_context
from del_social.agents.copywriter import CopyOption, CopyOutput, RevisedOptions
from del_social.agents.pipeline import generate_for_brief
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLMError, LLMResult
from del_social.llm.pricing import Usage

from .conftest import O

EVALS = Path(__file__).resolve().parents[3] / "evals"

PROFILE = BrandProfile.model_validate({
    "basics": {"company_name": "Del Furniture", "phone": "+994504448600", "whatsapp": "+994504448600",
               "website": "https://del-furniture.com/", "showroom_address": "Lökbatan"},
    "never": {"words": ["Ucuz", "Şok qiymət", "Tələsin"], "competitors": ["Embawood", "Saloglu", "Madeyra"]},
    "hashtags": {"branded": ["#DelFurniture"], "pool": ["#mebel"], "max_per_post": 10},
})
BRIEF = Brief(id="t1", topic="Wardrobe project", photo="White wardrobe")

GOOD = CopyOption(
    angle="craft",
    caption_az="Məkanınızın hər bir santimetrini dəyərləndirin. Fərdi qarderob layihəniz üçün bizimlə əlaqə saxlayın.",
    caption_ru="Ценим каждый сантиметр вашего пространства. Свяжитесь с нами для проекта шкафа.",
    hashtags=["#DelFurniture", "#mebel"],
    alt_text="Ağ qarderob",
)
CHEAP = GOOD.model_copy(update={"angle": "price", "caption_az": "Ucuz qarderob axtarırsınız? Bizimlə əlaqə saxlayın, fərdi həll təklif edirik."})


def rules(option: CopyOption, brief: Brief = BRIEF) -> set[str]:
    return {f.code for f in brand_guardian.rule_findings(PROFILE, brief, option)}


# --- deterministic checks ---


def test_az_lower_handles_dotted_i():
    assert az_lower("İSTƏK") == "istək" and az_lower("ISIQ") == "ısıq"


def test_guardian_eval_cases_rules():
    """The rule layer alone must catch every mechanical case in evals/brand_guardian/cases.yaml."""
    cases = {c["id"]: c for c in yaml.safe_load((EVALS / "brand_guardian" / "cases.yaml").read_text(encoding="utf-8"))}
    expected = {
        "bad-competitor": "competitor", "bad-never-word": "never_word", "bad-shock-price": "never_word",
        "bad-price-manat": "price", "bad-discount-percent": "price", "bad-phone": "phone_in_text",
        "bad-link": "link_in_text", "bad-too-many-hashtags": "too_many_hashtags",
        "bad-foreign-letter": "az_foreign_letter", "bad-cyrillic-in-az": "az_has_cyrillic",
        "bad-az-spelling": "az_not_azerbaijani",
    }
    for case_id, code in expected.items():
        c = cases[case_id]
        option = CopyOption(angle="x", alt_text="", **c["option"])
        assert code in rules(option, Brief.model_validate(c["brief"])), case_id
    for case_id in ("good-wardrobe", "good-office", "good-measurement"):
        c = cases[case_id]
        assert rules(CopyOption(angle="x", alt_text="", **c["option"]), Brief.model_validate(c["brief"])) == set(), case_id
    competitor = brand_guardian.rule_findings(
        PROFILE, BRIEF, CopyOption(angle="x", alt_text="", **cases["bad-competitor"]["option"])
    )
    assert any(f.code == "competitor" and f.severity == "block" for f in competitor)


def test_price_allowed_only_as_written_in_brief():
    offer = GOOD.model_copy(update={"caption_az": GOOD.caption_az + " 20% endirim."})
    assert "price" in rules(offer)
    with_text = Brief(id="t2", topic="Offer", photo="Kitchen", price_text="20% endirim")
    assert "price" not in rules(offer, with_text)


def test_caption_assembly_is_deterministic():
    caption = assemble_caption(PROFILE, "Azərbaycanca mətn.", "Русский текст.", ["#DelFurniture", "#mebel"])
    assert caption.split("\n\n") == [
        "Azərbaycanca mətn.",
        "Русский текст.",
        "📞 WhatsApp: +994504448600\n🌐 https://del-furniture.com/\n📍 Lökbatan",
        "#DelFurniture #mebel",
    ]
    az_only = PROFILE.model_copy(update={"languages": PROFILE.languages.model_copy(update={"mode": "az"})})
    assert "Русский" not in assemble_caption(az_only, "Mətn.", "Русский текст.", [])


def test_brand_context_hides_contacts():
    ctx = brand_context(PROFILE)
    assert "+994504448600" not in ctx and "del-furniture.com" not in ctx and "Embawood" in ctx


def test_eval_files_are_valid():
    briefs = yaml.safe_load((EVALS / "copywriter" / "briefs.yaml").read_text(encoding="utf-8"))
    assert len(briefs) >= 40
    assert len({b["id"] for b in briefs}) == len(briefs)
    for b in briefs:
        Brief.model_validate({k: v for k, v in b.items() if k != "review_hint"})
    cases = yaml.safe_load((EVALS / "brand_guardian" / "cases.yaml").read_text(encoding="utf-8"))
    assert len(cases) >= 20
    for c in cases:
        assert c["expect"] in ("pass", "fix", "block")
        Brief.model_validate(c["brief"])
        CopyOption(angle="x", alt_text="", **c["option"])


# --- fix loop with a scripted LLM ---


class FakeLLM:
    """Stands in for del_social.llm.LLM. Copywriter answers come from a script; the Guardian finds nothing."""

    def __init__(self, copy_script: list[list[CopyOption]], guardian_issues: dict[int, list] | None = None):
        self.copy_script = copy_script
        self.guardian_issues = guardian_issues or {}
        self.users: list[tuple[str, str]] = []
        self.revise_count: int | None = None  # force a wrong count to test the guard

    async def structured(self, *, tenant_id, prompt, user, output, tier, max_tokens, effort=None):
        self.users.append((prompt.agent, user))
        if output in (CopyOutput, RevisedOptions):
            opts = self.copy_script.pop(0) if len(self.copy_script) > 1 else self.copy_script[0]
            if output is RevisedOptions:
                n = int(re.search(r"Rewrite exactly (\d+)", user).group(1))
                out = RevisedOptions(options=opts[: self.revise_count if self.revise_count is not None else n])
            else:
                out = CopyOutput(options=opts)
        else:
            n = user.count('"index":')
            out = GuardianOutput(reviews=[OptionReview(index=i, issues=self.guardian_issues.get(i, [])) for i in range(n)])
        return LLMResult(out, "fake-model", Usage(10, 5), Decimal("0.010000"), 1, uuid.uuid4().hex)


async def test_fix_loop_rewrites_only_flagged_options():
    llm = FakeLLM([[GOOD, CHEAP, GOOD], [GOOD]])
    result = await generate_for_brief(llm, None, PROFILE, BRIEF)
    assert result["revisions"] == 1 and result["passed"] == 3
    assert [o["verdict"] for o in result["attempts"][0]["options"]] == ["pass", "fix", "pass"]
    assert result["attempts"][1]["rewritten"] == [1]
    assert [o["revised"] for o in result["options"]] == [False, True, False]
    calls = [(a, u) for a, u in llm.users]
    revise_prompt = calls[2][1]
    assert calls[2][0] == "copywriter"
    assert "<revision_request>" in revise_prompt and "Ucuz" in revise_prompt and "<kept_options>" in revise_prompt
    assert "Rewrite exactly 1 option" in revise_prompt
    assert calls[3][0] == "brand_guardian" and calls[3][1].count('"index":') == 1  # only the new option re-reviewed
    assert result["options"][0]["caption"].endswith("#DelFurniture #mebel")
    assert Decimal(result["cost_usd"]) == Decimal("0.040")


async def test_fix_loop_stops_after_two_revisions():
    llm = FakeLLM([[CHEAP, CHEAP, CHEAP]])
    result = await generate_for_brief(llm, None, PROFILE, BRIEF)
    assert result["revisions"] == 2 and result["passed"] == 0
    assert len([a for a, _ in llm.users if a == "copywriter"]) == 3


async def test_revision_with_wrong_count_is_an_error():
    llm = FakeLLM([[GOOD, CHEAP, CHEAP], [GOOD, GOOD, GOOD]])
    llm.revise_count = 1  # two were flagged, the model returns one
    with pytest.raises(LLMError, match="Expected 2"):
        await generate_for_brief(llm, None, PROFILE, BRIEF)


async def test_guardian_review_findings_and_missing_review():
    from del_social.agents.brand_guardian import ReviewIssue

    issue = ReviewIssue(category="spelling_az", severity="fix", note="'keyfiyetli' should be 'keyfiyyətli'")
    llm = FakeLLM([[GOOD, GOOD, GOOD]], guardian_issues={1: [issue]})
    verdicts, _ = await brand_guardian.review(llm, None, PROFILE, BRIEF, [GOOD, GOOD, GOOD])
    assert [v.verdict for v in verdicts] == ["pass", "fix", "pass"]
    assert verdicts[1].findings[0]["source"] == "review"

    class NoReview(FakeLLM):
        async def structured(self, **kw):
            r = await super().structured(**kw)
            return LLMResult(GuardianOutput(reviews=[]), r.model, r.usage, r.cost_usd, 1, r.trace_id)

    verdicts, _ = await brand_guardian.review(NoReview([[GOOD]]), None, PROFILE, BRIEF, [GOOD])
    assert verdicts[0].verdict == "fix"  # an unreviewed option never passes


# --- eval run storage + rating API ---


async def test_eval_run_is_stored_and_rated(client, admin, tenants, session_for, monkeypatch):
    from del_social.evals import run as runner

    await admin.execute(
        "INSERT INTO brand_profiles (tenant_id, version, data) VALUES ($1, 1, $2::jsonb)",
        tenants["a"], json.dumps(PROFILE.model_dump(mode="json")),
    )
    monkeypatch.setattr(runner, "build_llm", lambda settings, engine, http: FakeLLM([[GOOD, CHEAP, GOOD], [GOOD, GOOD, GOOD]]))
    briefs = [{"id": "b1", "topic": "Wardrobe", "photo": "Wardrobe", "review_hint": "only for humans"},
              {"id": "b2", "topic": "Kitchen", "photo": "Kitchen"}]
    run_id = await runner.run(tenants["a"], "copywriter", briefs)

    owner = await session_for(tenants["a_owner"])
    runs = (await client.get(f"/tenants/{tenants['a']}/evals", headers=owner)).json()
    assert runs[0]["run_id"] == str(run_id) and runs[0]["status"] == "done" and runs[0]["completed"] == 2
    detail = (await client.get(f"/tenants/{tenants['a']}/evals/{run_id}", headers=owner)).json()
    items = detail["items"]
    assert items[0]["brief"]["review_hint"] == "only for humans"
    assert all(len(i["result"]["options"]) == 3 for i in items)
    fake_prompts = "only for humans"
    assert fake_prompts not in json.dumps(items[0]["result"])  # the agents never saw the hint

    url = f"/tenants/{tenants['a']}/evals/{run_id}/items"
    r = await client.put(f"{url}/{items[0]['item_id']}", json={"ratings": {"0": "publishable", "1": "wrong", "2": "needs_edit"}}, headers={**owner, **O})
    assert r.status_code == 200, r.text
    await client.put(f"{url}/{items[1]['item_id']}", json={"ratings": {"0": "needs_edit", "1": "wrong", "2": "wrong"}, "note": "stiff"}, headers={**owner, **O})
    summary = (await client.get(f"/tenants/{tenants['a']}/evals/{run_id}", headers=owner)).json()
    assert (summary["rated"], summary["successes"], summary["success_rate"]) == (2, 1, 0.5)

    viewer = await session_for(tenants["a_viewer"])
    denied = await client.put(f"{url}/{items[0]['item_id']}", json={"ratings": {"0": "wrong"}}, headers={**viewer, **O})
    assert denied.status_code == 403
    owner_b = await session_for(tenants["b_owner"])
    assert (await client.get(f"/tenants/{tenants['b']}/evals/{run_id}", headers=owner_b)).status_code == 404
    bad = await client.put(f"{url}/{items[0]['item_id']}", json={"ratings": {"0": "great"}}, headers={**owner, **O})
    assert bad.status_code == 422
