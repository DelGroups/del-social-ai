# ADR 001: Tenant isolation with Postgres RLS plus app-level filters

- **Status:** Accepted
- **Date:** 2026-09-25
- **Phase:** 0

## Context

DEL SOCIAL AI is multi-tenant. Many companies share one database, and each company's data (users, channel tokens, content, DMs) must never be visible to another. A single missed `WHERE tenant_id = …` in application code, or in a tool an agent calls, would leak data between customers. That kind of bug is easy to write and hard to notice.

## Decision

Isolation is enforced in **two independent layers**:

1. **Database (Row-Level Security).** Every table with tenant data has a `tenant_id` column. RLS is `ENABLE`d and `FORCE`d on it, with a policy of the form `tenant_id = app_current_tenant_id()`, applied to both reads (`USING`) and writes (`WITH CHECK`).
2. **Application.** Code still filters by `tenant_id` explicitly. RLS is the safety net, not the only guard.

How it works:

- **Tenant context.** At the start of every transaction the app calls `set_tenant(session, tenant_id)`. This runs `set_config('app.tenant_id', …, true)`.
  - The setting is transaction-local, so it resets at commit or rollback. A pooled connection can't carry one tenant's scope into the next request.
  - There is no trigger that sets the context. The request itself must declare which tenant it acts for.
- **Fail closed.** If `app.tenant_id` is unset or empty, `app_current_tenant_id()` returns NULL and every tenant table returns zero rows. Writes are rejected.
- **Restricted runtime role.** Postgres superusers and roles with `BYPASSRLS` ignore RLS entirely. The `postgres` image's default user is a superuser. So:
  - Migration 0001 creates a `del_app` role with no superuser and no BYPASSRLS.
  - The API must connect as `del_app`. Only migrations and admin tasks use the owner account.
  - `FORCE ROW LEVEL SECURITY` also binds the table owner when the owner is not a superuser.
- **Convenience trigger.** `fill_tenant_id` fills a missing `tenant_id` from the context on insert (`users`, `tenant_secrets`). It is a convenience only; the policy still checks the result.
- **Tests as the gate.** `apps/api/tests/test_rls.py` runs in CI on every push. It covers:
  - two tenants each seeing only their own rows;
  - the context being empty after commit;
  - cross-tenant INSERT, UPDATE and DELETE being blocked;
  - `del_app` not being able to bypass RLS;
  - a schema guard that fails if any future table with a `tenant_id` column lacks forced RLS and a policy.

## Consequences

**Benefits**
- A forgotten filter in code, in an agent tool, or in a hand-written query cannot leak another tenant's data.
- The guarantee lives in one place (the policy) and is checked automatically, so reviewers don't have to verify every query.
- New tables inherit the rule through the migration checklist and the schema-guard test.

**Costs and trade-offs**
- **Every transaction must call `set_tenant`.** If it's forgotten, the request sees empty results rather than an error. This is safe, but bugs can look like "no data".
- **Two database roles to manage.** There is the owner (migrations) and `del_app` (runtime). `del_app` needs login and a password configured on each environment.
- **Cross-tenant work needs a deliberate privileged path.** Platform superadmin screens, billing and analytics across tenants can't simply query. They will use a separate, audited connection as a BYPASSRLS role.
- **Small per-query overhead.** The policy adds a predicate. `tenant_id` leads every tenant-scoped index, so the cost is negligible at our scale.
- **Tenant creation.** Under RLS, creating a tenant means setting the context to the new id first. In practice it's a platform operation done through the privileged path.

## Alternatives considered

| Option | Why not |
|---|---|
| App-level filtering only | One missed `WHERE` is a data leak, and agents generate queries through tools. It's too fragile for a B2B product holding other companies' tokens and DMs. |
| Schema per tenant | Migrations must run N times, pooling and cross-tenant ops get complicated, and it doesn't fit one small VPS. |
| Database per tenant | Strongest isolation but the highest operational cost. Worth revisiting only for a large customer with a contractual requirement. |

## Rollout

1. ✅ 2026-09-25: backup taken, then `alembic upgrade head` run on production as the owner.
2. ✅ 2026-09-25: `del_app` login enabled with a random password, stored only in the server's `.env` (`APP_DB_PASSWORD`).
3. The API's `DATABASE_URL` uses `del_app` (docker-compose.yml). The api container no longer receives the owner's credentials. Migrations run separately with `docker compose run --rm migrate`.
