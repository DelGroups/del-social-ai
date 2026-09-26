"""Brand profile: schema, versioning, roles and tenant isolation."""
import asyncpg
import pytest
from pydantic import ValidationError

from del_social.knowledge.brand_profile import BrandProfile, LanguageMode

from .conftest import O, as_app


def url(tenant_id, path=""):
    return f"/tenants/{tenant_id}/brand-profile{path}"


def profile(**basics) -> dict:
    data = BrandProfile().model_dump(mode="json")
    data["basics"] |= basics
    return data


# --- schema ---


def test_defaults_follow_phase_1_decisions():
    p = BrandProfile()
    assert p.languages.mode is LanguageMode.AZ_RU_SAME_CAPTION
    assert p.mention_prices is False
    assert any("Novruz" in o for o in p.occasions)
    assert p.terminology == []  # added later: saved profiles without it still load


def test_old_versions_still_load_when_fields_are_added():
    assert BrandProfile.model_validate({"basics": {"company_name": "Del Furniture"}}).basics.company_name == "Del Furniture"


def test_schema_rejects_junk():
    with pytest.raises(ValidationError):
        BrandProfile.model_validate({"unknown_section": {}})
    with pytest.raises(ValidationError):
        BrandProfile.model_validate({"hashtags": {"max_per_post": 31}})
    with pytest.raises(ValidationError):
        BrandProfile.model_validate({"never": {"words": [""]}})
    assert BrandProfile.model_validate({"ctas": ["  Zəng edin  "]}).ctas == ["Zəng edin"]


# --- API ---


async def test_save_creates_versions_and_keeps_history(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    empty = await client.get(url(tenants["a"]), headers=owner)
    assert empty.status_code == 200 and empty.json()["version"] == 0

    v1 = await client.put(url(tenants["a"]), json={"base_version": 0, "data": profile(company_name="Del Furniture")}, headers={**owner, **O})
    assert v1.status_code == 200, v1.text
    assert v1.json()["version"] == 1 and v1.json()["created_by_email"]
    v2 = await client.put(url(tenants["a"]), json={"base_version": 1, "data": profile(company_name="Del Furniture MMC")}, headers={**owner, **O})
    assert v2.json()["version"] == 2

    current = (await client.get(url(tenants["a"]), headers=owner)).json()
    assert current["version"] == 2 and current["data"]["basics"]["company_name"] == "Del Furniture MMC"
    history = (await client.get(url(tenants["a"], "/versions"), headers=owner)).json()
    assert [h["version"] for h in history] == [2, 1]
    old = (await client.get(url(tenants["a"], "/versions/1"), headers=owner)).json()
    assert old["data"]["basics"]["company_name"] == "Del Furniture"
    assert (await client.get(url(tenants["a"], "/versions/9"), headers=owner)).status_code == 404


async def test_stale_edit_is_refused(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    await client.put(url(tenants["a"]), json={"base_version": 0, "data": profile()}, headers={**owner, **O})
    stale = await client.put(url(tenants["a"]), json={"base_version": 0, "data": profile()}, headers={**owner, **O})
    assert stale.status_code == 409


async def test_roles_and_tenants(client, tenants, session_for):
    owner_a = await session_for(tenants["a_owner"])
    viewer_a = await session_for(tenants["a_viewer"])
    owner_b = await session_for(tenants["b_owner"])
    await client.put(url(tenants["a"]), json={"base_version": 0, "data": profile(company_name="Secret A")}, headers={**owner_a, **O})

    assert (await client.get(url(tenants["a"]), headers=viewer_a)).status_code == 200
    edit = await client.put(url(tenants["a"]), json={"base_version": 1, "data": profile()}, headers={**viewer_a, **O})
    assert edit.status_code == 403
    assert (await client.get(url(tenants["a"]), headers=owner_b)).status_code == 403
    b_view = (await client.get(url(tenants["b"]), headers=owner_b)).json()
    assert b_view["version"] == 0 and "Secret A" not in str(b_view)
    no_origin = await client.put(url(tenants["a"]), json={"base_version": 1, "data": profile()}, headers=owner_a)
    assert no_origin.status_code == 403


async def test_invalid_profile_is_rejected(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    bad = profile()
    bad["hashtags"]["max_per_post"] = 99
    r = await client.put(url(tenants["a"]), json={"base_version": 0, "data": bad}, headers={**owner, **O})
    assert r.status_code == 422


# --- database rules ---


async def test_history_cannot_be_rewritten(admin, tenants):
    await admin.execute(
        "INSERT INTO brand_profiles (tenant_id, version, data) VALUES ($1, 1, '{}')", tenants["a"]
    )
    for sql in ("UPDATE brand_profiles SET data = '{}'", "DELETE FROM brand_profiles"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with as_app(admin, tenants["a"]) as conn:
                await conn.execute(sql)


async def test_profiles_only_own_tenant(admin, tenants):
    for key in ("a", "b"):
        await admin.execute(
            "INSERT INTO brand_profiles (tenant_id, version, data) VALUES ($1, 1, $2::jsonb)",
            tenants[key],
            f'{{"tenant": "{key}"}}',
        )
    async with as_app(admin, tenants["b"]) as conn:
        rows = await conn.fetch("SELECT tenant_id FROM brand_profiles")
    assert [r["tenant_id"] for r in rows] == [tenants["b"]]
