"""LLM layer: pricing, prompt files, structured calls, llm_calls records, Langfuse traces, usage API.

Anthropic and Langfuse are replaced by httpx.MockTransport: no real calls, no cost.
"""
import base64
import json
import uuid
from decimal import Decimal
from pathlib import Path

import anthropic
import asyncpg
import httpx
import httpx2  # the Anthropic SDK's HTTP library
import pytest
from pydantic import BaseModel

from del_social.core.config import get_settings
from del_social.llm import LLM, LLMError, Tier, load_prompt
from del_social.llm.pricing import Usage, cost_usd
from del_social.llm.prompts import PromptNotFound
from del_social.llm.tracing import Tracer

from .conftest import as_app

API_KEY = "sk-ant-test-key-never-leaks"
LF_PUBLIC, LF_SECRET = "pk-lf-test", "sk-lf-test-secret"


class Caption(BaseModel):
    text: str
    hashtags: list[str]


# --- pricing ---


def test_cost_is_computed_from_tokens():
    assert cost_usd("claude-sonnet-5", Usage(input_tokens=1000, output_tokens=500)) == Decimal("0.007000")
    assert cost_usd("claude-haiku-4-5-20251001", Usage(cache_read_tokens=1_000_000)) == Decimal("0.100000")
    assert cost_usd("claude-opus-5-5", Usage(input_tokens=1_000_000, cache_write_tokens=1_000_000, output_tokens=1_000_000)) == Decimal("29.000000")
    assert cost_usd("some-unknown-model", Usage(input_tokens=10)) is None


# --- prompt files ---


def test_prompt_versions(tmp_path: Path):
    agent = tmp_path / "copywriter"
    agent.mkdir()
    (agent / "prompt.v1.md").write_text("first", encoding="utf-8")
    (agent / "prompt.v2.md").write_text("second\n", encoding="utf-8")
    (agent / "notes.md").write_text("ignored", encoding="utf-8")
    latest = load_prompt("copywriter", base=tmp_path)
    assert (latest.version, latest.text) == (2, "second")
    assert latest.ref.startswith("copywriter@v2#") and len(latest.sha) == 12
    assert load_prompt("copywriter", 1, base=tmp_path).text == "first"
    for bad in [("copywriter", 3), ("nobody", None), ("../etc", None)]:
        with pytest.raises(PromptNotFound):
            load_prompt(*bad, base=tmp_path)


def test_real_prompt_files_load():
    assert load_prompt("system_check").version >= 1


# --- structured calls ---


class FakeAnthropic:
    def __init__(self):
        self.requests: list[dict] = []
        self.status = 200
        self.text = json.dumps({"text": "Salam! Привет!", "hashtags": ["#DelFurniture"]})
        self.stop_reason = "end_turn"

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append({"headers": dict(request.headers), "body": body})
        if self.status != 200:
            return httpx2.Response(self.status, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})
        return httpx2.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": self.text}],
            "stop_reason": self.stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 300,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 800},
        })


class FakeLangfuse:
    def __init__(self):
        self.batches: list[dict] = []
        self.auth: list[str] = []
        self.versions: list[str | None] = []
        self.fail = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("down")
        self.auth.append(request.headers["authorization"])
        self.versions.append(request.headers.get("x-langfuse-ingestion-version"))
        assert request.url.path == "/api/public/otel/v1/traces"
        self.batches.append(json.loads(request.content))
        return httpx.Response(200, json={})


def span_attrs(span: dict) -> dict[str, str]:
    out = {}
    for a in span["attributes"]:
        v = a["value"]
        out[a["key"]] = v.get("stringValue", v.get("intValue", v.get("arrayValue")))
    return out


@pytest.fixture
def fakes(app_engine):
    fa, lf = FakeAnthropic(), FakeLangfuse()
    client = anthropic.AsyncAnthropic(
        api_key=API_KEY, max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(fa.handle))
    )
    tracer = Tracer(httpx.AsyncClient(transport=httpx.MockTransport(lf.handle)), "https://lf.test", LF_PUBLIC, LF_SECRET)
    llm = LLM(client, get_settings(), app_engine, tracer)
    return llm, fa, lf


async def call(llm: LLM, tenant_id, tier=Tier.DEFAULT):
    return await llm.structured(
        tenant_id=tenant_id, prompt=load_prompt("system_check"), user="Write a caption", output=Caption, tier=tier
    )


async def test_successful_call_is_structured_recorded_and_traced(fakes, admin, tenants):
    llm, fa, lf = fakes
    r = await call(llm, tenants["a"])
    assert r.output == Caption(text="Salam! Привет!", hashtags=["#DelFurniture"])
    assert r.model == "claude-sonnet-5"
    assert r.cost_usd == Decimal("0.005560")  # 1200*2 + 800*0.20 + 300*10 per million

    req = fa.requests[0]["body"]
    assert req["model"] == "claude-sonnet-5"
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"]["format"]["type"] == "json_schema"

    row = await admin.fetchrow("SELECT * FROM llm_calls WHERE trace_id = $1", r.trace_id)
    assert row["tenant_id"] == tenants["a"] and row["status"] == "ok" and row["agent"] == "system_check"
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"]) == (1200, 300, 800)
    assert row["cost_usd"] == Decimal("0.005560")
    assert row["prompt_ref"].startswith("system_check@v1#")

    assert lf.auth[0] == "Basic " + base64.b64encode(f"{LF_PUBLIC}:{LF_SECRET}".encode()).decode()
    assert lf.versions[0] == "4"
    span = lf.batches[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    attrs = span_attrs(span)
    assert span["traceId"] == r.trace_id and len(r.trace_id) == 32
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == "claude-sonnet-5"
    assert json.loads(attrs["langfuse.observation.usage_details"])["output"] == 300
    assert json.loads(attrs["langfuse.observation.cost_details"])["total"] == pytest.approx(0.00556)
    assert attrs["langfuse.user.id"] == str(tenants["a"])
    assert attrs["langfuse.observation.prompt.version"] == "1"
    assert "Salam" in attrs["langfuse.observation.output"]
    assert API_KEY not in json.dumps(lf.batches)


async def test_tiers_pick_models(fakes, tenants):
    llm, fa, _ = fakes
    await call(llm, tenants["a"], Tier.FAST)
    await call(llm, tenants["a"], Tier.STRATEGY)
    assert [r["body"]["model"] for r in fa.requests] == ["claude-haiku-4-5-20251001", "claude-opus-5-5"]


async def test_failed_call_is_recorded_and_raised(fakes, admin, tenants):
    llm, fa, lf = fakes
    fa.status = 500
    with pytest.raises(LLMError) as e:
        await call(llm, tenants["a"])
    assert API_KEY not in str(e.value)
    row = await admin.fetchrow("SELECT * FROM llm_calls WHERE tenant_id = $1", tenants["a"])
    assert row["status"] == "error" and "500" in row["error"]
    span = lf.batches[0]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["status"]["code"] == 2 and span_attrs(span)["langfuse.observation.level"] == "ERROR"


async def test_output_that_breaks_the_schema_is_an_error(fakes, admin, tenants):
    llm, fa, _ = fakes
    fa.text = json.dumps({"text": "no hashtags field"})
    with pytest.raises(LLMError):
        await call(llm, tenants["a"])
    assert await admin.fetchval("SELECT status FROM llm_calls WHERE tenant_id = $1", tenants["a"]) == "error"


async def test_langfuse_outage_does_not_break_calls(fakes, tenants):
    llm, _, lf = fakes
    lf.fail = True
    r = await call(llm, tenants["a"])
    assert r.output.text


async def test_platform_call_without_tenant_is_not_recorded(fakes, admin):
    llm, _, _ = fakes
    before = await admin.fetchval("SELECT count(*) FROM llm_calls")
    await call(llm, None)
    assert await admin.fetchval("SELECT count(*) FROM llm_calls") == before


# --- database rules ---


async def test_usage_history_cannot_be_rewritten_or_seen_across_tenants(admin, tenants):
    for key in ("a", "b"):
        await admin.execute(
            "INSERT INTO llm_calls (tenant_id, agent, prompt_ref, model, status, latency_ms, trace_id, cost_usd)"
            " VALUES ($1, 'copywriter', 'copywriter@v1#x', 'claude-sonnet-5', 'ok', 10, $2, 0.01)",
            tenants[key], str(uuid.uuid4()),
        )
    async with as_app(admin, tenants["a"]) as conn:
        assert [r["tenant_id"] for r in await conn.fetch("SELECT tenant_id FROM llm_calls")] == [tenants["a"]]
    for sql in ("UPDATE llm_calls SET cost_usd = 0", "DELETE FROM llm_calls"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with as_app(admin, tenants["a"]) as conn:
                await conn.execute(sql)


# --- usage API ---


async def test_usage_report(client, admin, tenants, session_for):
    rows = [("a", "copywriter", "ok", "0.010000"), ("a", "copywriter", "error", "0.002000"),
            ("a", "brand_guardian", "ok", "0.001000"), ("b", "copywriter", "ok", "5.000000")]
    for key, agent, status_, cost in rows:
        await admin.execute(
            "INSERT INTO llm_calls (tenant_id, agent, prompt_ref, model, status, input_tokens, output_tokens,"
            " latency_ms, trace_id, cost_usd) VALUES ($1, $2, 'p', 'claude-sonnet-5', $3, 100, 50, 10, $4, $5)",
            tenants[key], agent, status_, str(uuid.uuid4()), Decimal(cost),
        )
    owner = await session_for(tenants["a_owner"])
    r = await client.get(f"/tenants/{tenants['a']}/usage", headers=owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["calls"] == 3 and Decimal(body["cost_usd"]) == Decimal("0.013")
    by = {a["agent"]: a for a in body["by_agent"]}
    assert by["copywriter"]["calls"] == 2 and by["copywriter"]["errors"] == 1
    assert body["by_agent"][0]["agent"] == "copywriter"  # most expensive first

    old = (await client.get(f"/tenants/{tenants['a']}/usage?month=2020-01", headers=owner)).json()
    assert old["calls"] == 0 and old["month"] == "2020-01"
    assert (await client.get(f"/tenants/{tenants['a']}/usage?month=soon", headers=owner)).status_code == 422
    viewer = await session_for(tenants["a_viewer"])
    assert (await client.get(f"/tenants/{tenants['a']}/usage", headers=viewer)).status_code == 403


async def test_cut_off_output_still_records_tokens(fakes, admin, tenants):
    llm, fa, _ = fakes
    fa.stop_reason = "max_tokens"
    fa.text = '{"text": "Salam'
    with pytest.raises(LLMError, match="cut off"):
        await call(llm, tenants["a"])
    row = await admin.fetchrow("SELECT * FROM llm_calls WHERE tenant_id = $1", tenants["a"])
    assert row["status"] == "error" and row["output_tokens"] == 300 and row["cost_usd"] > 0


async def test_invalid_output_error_names_the_field(fakes, admin, tenants):
    llm, fa, _ = fakes
    fa.text = json.dumps({"text": "no hashtags field"})
    with pytest.raises(LLMError, match="hashtags"):
        await call(llm, tenants["a"])
    assert await admin.fetchval("SELECT input_tokens FROM llm_calls WHERE tenant_id = $1", tenants["a"]) == 1200
