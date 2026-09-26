"""HTTP endpoints through the real app, as del_app on real Postgres + Redis (ADR 002)."""
import re
import uuid

import httpx
import pytest

from del_social.cli import CliError, create_platform_admin, set_password
from del_social.core.security import hash_password, verify_password
from del_social.core.sessions import SESSION_COOKIE

from .conftest import O, cookie, plain_dsn

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new passphrase"


def session_token(response: httpx.Response) -> str:
    m = re.search(rf"{re.escape(SESSION_COOKIE)}=([^;]+)", response.headers.get("set-cookie", ""))
    assert m, "no session cookie set"
    return m.group(1)


def link_token(url: str) -> str:
    return url.rsplit("/", 1)[1]


def new_email() -> str:
    return f"{uuid.uuid4()}@route.test"


@pytest.fixture
async def login_account(account_factory) -> tuple[uuid.UUID, str]:
    email = new_email()
    return await account_factory(email, password_hash=hash_password(PASSWORD)), email


@pytest.fixture
async def cleanup(admin):
    """Tenants and accounts created through the API during a test."""
    state: dict[str, list] = {"tenants": [], "emails": []}
    yield state
    await admin.execute(
        "DELETE FROM memberships WHERE account_id IN (SELECT account_id FROM accounts WHERE email = ANY($1))",
        state["emails"],
    )
    for table in ("connections", "invitations", "memberships", "tenant_secrets", "tenants"):
        await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", state["tenants"])
    await admin.execute("DELETE FROM accounts WHERE email = ANY($1)", state["emails"])


async def add_member(admin, tenant_id, account_id, role) -> uuid.UUID:
    return await admin.fetchval(
        "INSERT INTO memberships (tenant_id, account_id, role) VALUES ($1, $2, $3) RETURNING membership_id",
        tenant_id,
        account_id,
        role,
    )


async def membership_id(admin, tenant_id, account_id) -> uuid.UUID:
    return await admin.fetchval(
        "SELECT membership_id FROM memberships WHERE tenant_id = $1 AND account_id = $2",
        tenant_id,
        account_id,
    )


async def email_of(admin, account_id) -> str:
    return await admin.fetchval("SELECT email FROM accounts WHERE account_id = $1", account_id)


# --- sign-in / sign-out / password ---


async def test_login_sets_hardened_session_cookie(client, login_account):
    account_id, email = login_account
    r = await client.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=O)
    assert r.status_code == 200
    assert r.json()["account_id"] == str(account_id)
    set_cookie = r.headers["set-cookie"].lower()
    for attribute in ("httponly", "secure", "samesite=lax", "path=/"):
        assert attribute in set_cookie
    assert set_cookie.startswith(SESSION_COOKIE.lower() + "=")


async def test_login_failures(client, login_account):
    _, email = login_account
    wrong = await client.post("/auth/login", json={"email": email, "password": "nope nope nope"}, headers=O)
    unknown = await client.post("/auth/login", json={"email": new_email(), "password": PASSWORD}, headers=O)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    no_origin = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert no_origin.status_code == 403


async def test_me_and_logout(client, admin, login_account, tenants):
    account_id, email = login_account
    await add_member(admin, tenants["a"], account_id, "approver")
    token = session_token(
        await client.post("/auth/login", json={"email": email, "password": PASSWORD}, headers=O)
    )
    me = await client.get("/auth/me", headers=cookie(token))
    assert me.status_code == 200
    assert me.json()["memberships"] == [
        {"tenant_id": str(tenants["a"]), "tenant_name": "Tenant A", "role": "approver"}
    ]
    assert (await client.post("/auth/logout", headers=cookie(token) | O)).status_code == 204
    assert (await client.get("/auth/me", headers=cookie(token))).status_code == 401
    assert (await client.get("/auth/me")).status_code == 401


async def test_change_password_signs_out_other_sessions(client, session_for, login_account):
    account_id, email = login_account
    mine, other = await session_for(account_id), await session_for(account_id)
    bad = await client.post(
        "/auth/password", json={"current_password": "wrong wrong", "new_password": NEW_PASSWORD}, headers=mine | O
    )
    assert bad.status_code == 403
    weak = await client.post(
        "/auth/password", json={"current_password": PASSWORD, "new_password": "short"}, headers=mine | O
    )
    assert weak.status_code == 422
    ok = await client.post(
        "/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}, headers=mine | O
    )
    assert ok.status_code == 204
    assert (await client.get("/auth/me", headers=mine)).status_code == 200
    assert (await client.get("/auth/me", headers=other)).status_code == 401
    relogin = await client.post("/auth/login", json={"email": email, "password": NEW_PASSWORD}, headers=O)
    assert relogin.status_code == 200


# --- invitations ---


async def invite(client, headers, tenant_id, email, role="viewer") -> httpx.Response:
    return await client.post(
        f"/tenants/{tenant_id}/invitations", json={"email": email, "role": role}, headers=headers | O
    )


async def test_new_person_accepts_invitation(client, tenants, session_for, cleanup):
    owner = await session_for(tenants["a_owner"])
    email = new_email()
    cleanup["emails"].append(email)
    r = await invite(client, owner, tenants["a"], email.upper(), "approver")
    assert r.status_code == 201
    url = r.json()["url"]
    assert url.startswith("https://app.test/invite/")
    token = link_token(url)

    info = await client.get(f"/auth/invitations/{token}")
    assert info.json() == {"tenant_name": "Tenant A", "email": email, "role": "approver", "status": "pending"}

    assert (await client.post(f"/auth/invitations/{token}/accept", json={}, headers=O)).status_code == 422
    short = await client.post(f"/auth/invitations/{token}/accept", json={"password": "short"}, headers=O)
    assert short.status_code == 422
    accepted = await client.post(f"/auth/invitations/{token}/accept", json={"password": PASSWORD}, headers=O)
    assert accepted.status_code == 200
    assert accepted.json()["memberships"] == [
        {"tenant_id": str(tenants["a"]), "tenant_name": "Tenant A", "role": "approver"}
    ]
    new_session = session_token(accepted)
    assert (await client.get("/auth/me", headers=cookie(new_session))).status_code == 200

    again = await client.post(f"/auth/invitations/{token}/accept", json={"password": PASSWORD}, headers=O)
    assert again.status_code == 410
    members = (await client.get(f"/tenants/{tenants['a']}/members", headers=owner)).json()
    assert {(m["email"], m["role"]) for m in members} >= {(email, "approver")}


async def test_existing_account_must_sign_in_to_accept(client, tenants, session_for, login_account):
    account_id, email = login_account
    owner = await session_for(tenants["a_owner"])
    token = link_token((await invite(client, owner, tenants["a"], email)).json()["url"])
    anonymous = await client.post(f"/auth/invitations/{token}/accept", json={"password": PASSWORD}, headers=O)
    assert anonymous.status_code == 409
    signed_in = await client.post(
        f"/auth/invitations/{token}/accept", json={}, headers=await session_for(account_id) | O
    )
    assert signed_in.status_code == 200
    assert [m["tenant_id"] for m in signed_in.json()["memberships"]] == [str(tenants["a"])]


async def test_invitation_for_someone_else_is_refused(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    token = link_token((await invite(client, owner, tenants["a"], new_email())).json()["url"])
    r = await client.post(
        f"/auth/invitations/{token}/accept", json={}, headers=await session_for(tenants["b_owner"]) | O
    )
    assert r.status_code == 403


async def test_expired_and_revoked_invitations(client, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    expired = (await invite(client, owner, tenants["a"], new_email())).json()
    await admin.execute(
        "UPDATE invitations SET expires_at = now() - interval '1 second' WHERE invitation_id = $1",
        uuid.UUID(expired["invitation_id"]),
    )
    token = link_token(expired["url"])
    assert (await client.get(f"/auth/invitations/{token}")).json()["status"] == "expired"
    assert (await client.post(f"/auth/invitations/{token}/accept", json={"password": PASSWORD}, headers=O)).status_code == 410

    revoked = (await invite(client, owner, tenants["a"], new_email())).json()
    r = await client.delete(f"/tenants/{tenants['a']}/invitations/{revoked['invitation_id']}", headers=owner | O)
    assert r.status_code == 204
    assert (await client.get(f"/auth/invitations/{link_token(revoked['url'])}")).json()["status"] == "revoked"


async def test_unknown_invitation_token(client):
    assert (await client.get("/auth/invitations/not-a-real-token")).status_code == 404


async def test_who_may_invite_whom(client, admin, tenants, session_for, account_factory):
    admin_account = await account_factory()
    await add_member(admin, tenants["a"], admin_account, "admin")
    viewer = await session_for(tenants["a_viewer"])
    tenant_admin = await session_for(admin_account)
    owner = await session_for(tenants["a_owner"])
    assert (await invite(client, viewer, tenants["a"], new_email())).status_code == 403
    assert (await invite(client, tenant_admin, tenants["a"], new_email(), "approver")).status_code == 201
    assert (await invite(client, tenant_admin, tenants["a"], new_email(), "owner")).status_code == 403
    assert (await invite(client, owner, tenants["a"], new_email(), "owner")).status_code == 201


async def test_no_duplicate_invitations(client, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    member_email = await email_of(admin, tenants["a_viewer"])
    assert (await invite(client, owner, tenants["a"], member_email)).status_code == 409
    email = new_email()
    assert (await invite(client, owner, tenants["a"], email)).status_code == 201
    assert (await invite(client, owner, tenants["a"], email)).status_code == 409
    assert (await invite(client, owner, tenants["a"], "not-an-email")).status_code == 422


async def test_pending_invitations_list_never_shows_links(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    email = new_email()
    await invite(client, owner, tenants["a"], email)
    listed = (await client.get(f"/tenants/{tenants['a']}/invitations", headers=owner)).json()
    assert [i["email"] for i in listed] == [email]
    assert "url" not in listed[0]


async def test_cannot_touch_another_tenants_invitations(client, tenants, session_for):
    b_owner = await session_for(tenants["b_owner"])
    a_owner = await session_for(tenants["a_owner"])
    b_invitation = (await invite(client, b_owner, tenants["b"], new_email())).json()["invitation_id"]
    via_own_tenant = await client.delete(f"/tenants/{tenants['a']}/invitations/{b_invitation}", headers=a_owner | O)
    assert via_own_tenant.status_code == 404
    via_their_tenant = await client.delete(f"/tenants/{tenants['b']}/invitations/{b_invitation}", headers=a_owner | O)
    assert via_their_tenant.status_code == 403
    assert (await client.get(f"/tenants/{tenants['b']}/invitations", headers=a_owner)).status_code == 403


# --- members ---


async def test_members_list_is_tenant_scoped(client, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    members = (await client.get(f"/tenants/{tenants['a']}/members", headers=owner)).json()
    assert {m["email"] for m in members} == {
        await email_of(admin, tenants["a_owner"]),
        await email_of(admin, tenants["a_viewer"]),
    }
    assert (await client.get(f"/tenants/{tenants['b']}/members", headers=owner)).status_code == 403


async def test_last_owner_is_protected(client, admin, tenants, session_for, account_factory):
    owner = await session_for(tenants["a_owner"])
    own_membership = await membership_id(admin, tenants["a"], tenants["a_owner"])
    url = f"/tenants/{tenants['a']}/members/{own_membership}"
    assert (await client.patch(url, json={"role": "admin"}, headers=owner | O)).status_code == 409
    assert (await client.delete(url, headers=owner | O)).status_code == 409
    await add_member(admin, tenants["a"], await account_factory(), "owner")
    demoted = await client.patch(url, json={"role": "admin"}, headers=owner | O)
    assert demoted.status_code == 200 and demoted.json()["role"] == "admin"


async def test_admin_cannot_manage_owners(client, admin, tenants, session_for, account_factory):
    admin_account = await account_factory()
    await add_member(admin, tenants["a"], admin_account, "admin")
    tenant_admin = await session_for(admin_account)
    owner_m = await membership_id(admin, tenants["a"], tenants["a_owner"])
    viewer_m = await membership_id(admin, tenants["a"], tenants["a_viewer"])
    base = f"/tenants/{tenants['a']}/members"
    assert (await client.patch(f"{base}/{owner_m}", json={"role": "viewer"}, headers=tenant_admin | O)).status_code == 403
    assert (await client.delete(f"{base}/{owner_m}", headers=tenant_admin | O)).status_code == 403
    assert (await client.patch(f"{base}/{viewer_m}", json={"role": "owner"}, headers=tenant_admin | O)).status_code == 403
    ok = await client.patch(f"{base}/{viewer_m}", json={"role": "approver"}, headers=tenant_admin | O)
    assert ok.status_code == 200 and ok.json()["role"] == "approver"
    assert (await client.delete(f"{base}/{viewer_m}", headers=tenant_admin | O)).status_code == 204


async def test_other_tenants_membership_is_not_found(client, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    b_membership = await membership_id(admin, tenants["b"], tenants["b_owner"])
    r = await client.delete(f"/tenants/{tenants['a']}/members/{b_membership}", headers=owner | O)
    assert r.status_code == 404
    assert await membership_id(admin, tenants["b"], tenants["b_owner"]) == b_membership


# --- platform admin ---


async def test_platform_routes_need_platform_admin(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    r = await client.post("/platform/tenants", json={"name": "X", "owner_email": new_email()}, headers=owner | O)
    assert r.status_code == 403
    r = await client.post("/platform/password-resets", json={"email": new_email()}, headers=owner | O)
    assert r.status_code == 403


async def test_platform_admin_creates_tenant_for_new_owner(client, account_factory, session_for, cleanup):
    platform_admin = await session_for(await account_factory(is_platform_admin=True))
    owner_email = new_email()
    cleanup["emails"].append(owner_email)
    r = await client.post(
        "/platform/tenants", json={"name": "Del Furniture Test", "owner_email": owner_email}, headers=platform_admin | O
    )
    assert r.status_code == 201
    body = r.json()
    cleanup["tenants"].append(uuid.UUID(body["tenant_id"]))

    accepted = await client.post(
        f"/auth/invitations/{link_token(body['owner_invitation_url'])}/accept", json={"password": PASSWORD}, headers=O
    )
    assert accepted.json()["memberships"] == [
        {"tenant_id": body["tenant_id"], "tenant_name": "Del Furniture Test", "role": "owner"}
    ]
    # Being a platform admin grants no access to tenant data
    r = await client.get(f"/tenants/{body['tenant_id']}/members", headers=platform_admin)
    assert r.status_code == 403


async def test_password_reset_link(client, account_factory, session_for, login_account):
    account_id, email = login_account
    old_session = await session_for(account_id)
    platform_admin = await session_for(await account_factory(is_platform_admin=True))
    missing = await client.post("/platform/password-resets", json={"email": new_email()}, headers=platform_admin | O)
    assert missing.status_code == 404
    issued = await client.post("/platform/password-resets", json={"email": email}, headers=platform_admin | O)
    assert issued.status_code == 201
    url = issued.json()["url"]
    assert url.startswith("https://app.test/reset-password/")
    token = link_token(url)

    info = await client.get(f"/auth/password-resets/{token}")
    assert info.status_code == 200 and info.json() == {"email": email}

    weak = await client.post(f"/auth/password-resets/{token}", json={"new_password": "short"}, headers=O)
    assert weak.status_code == 422
    used = await client.post(f"/auth/password-resets/{token}", json={"new_password": NEW_PASSWORD}, headers=O)
    assert used.status_code == 204
    assert (await client.get("/auth/me", headers=old_session)).status_code == 401
    assert (await client.post("/auth/login", json={"email": email, "password": NEW_PASSWORD}, headers=O)).status_code == 200
    reused = await client.post(f"/auth/password-resets/{token}", json={"new_password": NEW_PASSWORD}, headers=O)
    assert reused.status_code == 410
    assert (await client.get(f"/auth/password-resets/{token}")).status_code == 410


# --- CLI ---


async def test_cli_creates_platform_admin(admin, migrated_db):
    email = new_email()
    try:
        account_id = await create_platform_admin(plain_dsn(migrated_db), email.upper(), PASSWORD)
        row = await admin.fetchrow(
            "SELECT email, password_hash, is_platform_admin FROM accounts WHERE account_id = $1", account_id
        )
        assert row["email"] == email and row["is_platform_admin"]
        assert verify_password(PASSWORD, row["password_hash"])
        with pytest.raises(CliError):
            await create_platform_admin(plain_dsn(migrated_db), email, PASSWORD)
        with pytest.raises(CliError):
            await create_platform_admin(plain_dsn(migrated_db), new_email(), "short")
    finally:
        await admin.execute("DELETE FROM accounts WHERE email = $1", email)


async def test_cli_set_password_signs_out_everywhere(client, session_for, login_account, migrated_db):
    account_id, email = login_account
    old_session = await session_for(account_id)
    await set_password(plain_dsn(migrated_db), email.upper(), NEW_PASSWORD)
    assert (await client.get("/auth/me", headers=old_session)).status_code == 401
    ok = await client.post("/auth/login", json={"email": email, "password": NEW_PASSWORD}, headers=O)
    assert ok.status_code == 200
    with pytest.raises(CliError):
        await set_password(plain_dsn(migrated_db), new_email(), NEW_PASSWORD)
