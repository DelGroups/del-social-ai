# ADR 002: Authentication with global accounts and per-tenant memberships

- **Status:** Accepted. Alireza approved the three product decisions on 2026-09-25. Implementation details below may be refined in PRs; any change to a decision needs a new ADR.
- **Date:** 2026-09-25
- **Phase:** 0
- **Builds on:** [ADR 001: Tenant isolation with RLS](001-multi-tenant-rls.md)

## Context

The panel needs sign-in and the four tenant roles (owner, admin, approver, viewer) plus a platform superadmin. Three product decisions were made:

1. **Sign-in method:** email + password. Google sign-in may come later.
2. **One login, many companies:** a person (an agency, or Alireza) can belong to several tenants with **one** account and a different role in each.
3. **No email service in Phase 0:** new users join via invitation links that an owner or admin copies from the panel and sends themselves. Self-service "forgot password" by email comes later.

The hard problem is sign-in under RLS. At login we know only an email, not the tenant. The current `users` table is tenant-scoped and returns no rows until `app.tenant_id` is set. Login must work without weakening that rule.

## Decision

### Data model: identity is global, access is per tenant

| Table | Scope | Purpose |
|---|---|---|
| `accounts` | **global** (no `tenant_id`) | One per person: `email` (unique, lowercase), `password_hash`, `is_active`, `is_platform_admin`, `last_login_at` |
| `memberships` | **tenant** (RLS, ADR 001) | `(tenant_id, account_id, role)`, unique per `(tenant_id, account_id)`. Replaces today's `users` table. Production has 0 rows, so migration 0002 renames and reshapes it safely. |
| `auth_sessions` | **account** | Server-side sessions: `token_hash` (SHA-256), `expires_at`, `idle_expires_at`, `revoked_at`, `user_agent`, `ip` |
| `invitations` | **tenant** (RLS) | `email`, `role`, `token_hash`, `invited_by`, `expires_at` (7 days), `accepted_at`, `revoked_at` |
| `password_resets` | **account** | One-time reset links issued by a platform admin: `token_hash`, `expires_at` (1 hour), `used_at` |

`tenant_secrets` is unchanged.

### How the global tables stay protected

`accounts`, `auth_sessions` and `password_resets` have no tenant, so they get their own RLS policy: `account_id = app_current_account_id()`, read from a transaction-local `app.account_id` setting, the same pattern as `app.tenant_id`. After sign-in, `del_app` can see only the signed-in person's own account and sessions.

The few steps that must happen *before* we know who the caller is go through narrow `SECURITY DEFINER` SQL functions. These run with the owner's rights but return only what that one step needs, and each has `SET search_path = public, pg_temp`:

| Function | Returns | Used by |
|---|---|---|
| `auth_login_lookup(email)` | `account_id, password_hash, is_active` for that email only | login |
| `auth_session_account(token_hash)` | `account_id` if the session is valid, else nothing | every authenticated request |
| `auth_my_memberships()` | tenants and roles of `app.account_id` | tenant switcher after login |
| `auth_invitation_by_token(token_hash)` | the invitation's tenant name, email, role and state | accepting an invitation |
| `auth_password_reset_by_token(token_hash)` | `account_id` if the reset link is valid and unused | using a reset link |

`EXECUTE` on these is revoked from `PUBLIC` and granted to `del_app` only. `del_app` gets **no** blanket read access to the global tables.

### Request flow

1. **Login.** `POST /auth/login {email, password}` runs `auth_login_lookup` and verifies the hash.
   - On success it creates a session and returns the account's tenants.
   - On any failure it returns the same generic error. If the email doesn't exist, a dummy hash is still verified, so response timing doesn't reveal which emails exist.
2. **Every request.** Session cookie → `auth_session_account` → `account_id`. The route names the tenant (`/tenants/{tenant_id}/…`). In one transaction the server:
   - sets `app.account_id` and `app.tenant_id`;
   - loads the caller's membership in that tenant. RLS already limits the rows to that tenant.
   - If there is no membership, the answer is **403**. A `tenant_id` sent by the client is never trusted on its own; the membership row is the proof.
3. **Roles.** A FastAPI dependency `require_role(...)` checks the membership's role against a permission table kept in one place in code.

### Sessions, not JWT

The session token is opaque, random (32 bytes), and stored in the database only as its SHA-256 hash.

- **Why:** we run one server, so JWT's statelessness buys nothing. Server-side sessions can be revoked instantly (logout, password change, a removed member), and there is no refresh-token rotation to get wrong.
- **Lifetime:** 30 days absolute, 7 days idle. The token is rotated at login.
- **Revocation:** changing a password revokes all of that account's other sessions.
- **Cookie:** `__Host-del_session`, with `Secure`, `HttpOnly`, `SameSite=Lax` and `Path=/`.
- **Same origin:** the panel calls the API through a proxy on `app.del-groups.com` (`/api/*` → `api:8000`). So the cookie lives on the panel's own origin, server-rendered pages can read it, and the browser needs no CORS. `api.del-groups.com` stays for webhooks and media.
- **CSRF:** state-changing requests must come from our own `Origin`. Together with `SameSite=Lax`, this blocks cross-site requests.

### Passwords

- **Hashing:** argon2id (`argon2-cffi`, library defaults, which follow the OWASP recommendation). Hashes are rehashed on login if the parameters change.
- **Policy:** 10 to 128 characters. There are no composition rules such as "one uppercase and one digit". NIST advises against them because they push people toward predictable passwords. A breached-password check may come later.
- **Logging:** passwords, hashes and tokens are never logged or returned in any response.

### Rate limiting

Counters live in Redis, since we already run it:

- **Failed logins:** 10 per 15 minutes per email, and 30 per 15 minutes per IP. Beyond that the answer is `429`.
- **Invitation acceptance:** limited per IP.

### Invitations and new users (no email in Phase 0)

1. **Invite.** An owner or admin invites `email + role` for their tenant. The panel shows a one-time link `https://app.del-groups.com/invite/<token>` for them to copy and send. Admins cannot invite owners.
2. **Accept.**
   - If an account with that email already exists: the person signs in, and **the signed-in email must match the invitation**. The membership is then created.
   - If no account exists: the person chooses a password, and the account and membership are created together.
3. **Single use.** An invitation can be used once, expires after 7 days, and can be revoked.

### Password reset (no email in Phase 0)

- **Signed-in users** change their own password, which requires the current password.
- **Forgotten passwords:** only a **platform admin** can issue a reset link (valid 1 hour, single use), and delivers it personally.
- **Why tenant admins cannot do this:** an account can belong to several companies. If the admin of company A could reset the password of someone who is also a member of company B, A could take over that person's access to B.
- **Later:** self-service reset by email arrives with the email service (next phase).

### Platform admin and tenant creation

- **No public signup in Phase 0.** Self-serve onboarding is a Phase 5 task.
- **Tenants are created by a platform admin** (`accounts.is_platform_admin`), together with their first owner invitation. The two test tenants for the Phase 0 done criterion are created the same way.
- **The first platform admin** (Alireza) is created by a one-off command run on the server with his approval: `docker compose run --rm api python -m del_social.cli create-platform-admin`. The password is typed at a prompt, never passed as an argument.
- **Being a platform admin gives no access to tenant data.** To work inside a tenant, a platform admin needs a membership like anyone else.

### Invariants enforced in code and tested

- A tenant always has at least one owner. The last owner cannot be removed or demoted.
- Removing a membership revokes nothing else, but that person immediately loses access to the tenant, because every request re-checks membership.
- Emails are stored lowercase, which a database CHECK constraint enforces.

## Threat model note

RLS protects against **application bugs**: a forgotten filter, a wrong tenant id, an agent tool that queries too broadly. It is not a defence against **SQL injection**. A caller who can run arbitrary SQL as `del_app` could also call `set_config`. SQL injection is prevented separately: all queries go through SQLAlchemy with bound parameters, and no raw string SQL is built from input.

## Consequences

**Benefits**
- Login works under RLS without any role that bypasses it. The pre-login database surface is five small, testable functions.
- One person can hold access to many companies, which fits agencies and our own team.
- Sessions can be revoked instantly. There are no JWT secrets to rotate and no refresh-token logic.
- No external email service or cost in Phase 0.

**Costs**
- `SECURITY DEFINER` functions need care: a fixed `search_path`, minimal outputs, and tests of exactly what each one returns.
- A database lookup on every request to validate the session. It's negligible at our scale, and can be cached in Redis later if needed.
- Manual delivery of invitation and reset links until email exists. That's acceptable for tenant #1 and the first customers.
- Migration 0002 replaces `users` with `accounts` + `memberships`. This is cheap now (0 production rows) and would be expensive later.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep `users` per tenant (same email = separate users) | Separate passwords per company for the same person, and login still has to guess the tenant |
| Tenant chosen before login (subdomain or tenant slug) | Extra step for every user, and it doesn't solve multi-company access |
| JWT access + refresh tokens | Harder to revoke, and more moving parts, with no benefit on a single server |
| A second DB role that bypasses RLS for auth | A whole connection with full access to auth tables, where five narrow functions are enough |
| Google sign-in now | Not every Azerbaijani SME has Google business accounts. Deferred, and addable later as an extra login method on `accounts` |

## Implementation plan (small PRs, each merged by Alireza after green CI)

1. **Schema.** Migration 0002 (accounts, memberships, sessions, invitations, password_resets, RLS policies, definer functions), models, and tests covering every policy and exactly what each function returns.
2. **Auth core.** Password hashing, session tokens, the request-context dependency (session → account → membership → `set_config`), `require_role`, Redis rate limiting, and tests.
3. **Endpoints.** Login/logout/me, my tenants, invitations (create/list/revoke/accept), change password, platform admin (create tenant, issue reset link), the `create-platform-admin` CLI, and tests, including cross-tenant attacks.
4. **Panel.** Same-origin `/api` proxy, sign-in page, invitation-accept page, tenant switcher, route protection.
5. **Production rollout (each step approved separately).**
   - Run migration 0002 on production.
   - Create Alireza's platform-admin account.
   - Create the two test tenants. This meets the Phase 0 done criterion.
