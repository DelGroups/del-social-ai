# ADR 004: Migrations run automatically on deploy, after a backup

- **Status:** Accepted. Alireza approved on 2026-09-26.
- **Date:** 2026-09-26
- **Phase:** 1
- **Changes:** the "migrations run separately" step in [ADR 001](001-multi-tenant-rls.md)

## Context

Until now, every new table needed a manual step after the PR was merged: take a backup, then run `docker compose run --rm migrate`. Between the merge and that step, the new code was live against the old schema, and the affected pages returned errors. Phase 1 adds several tables, so this gap would recur with each one.

## Decision

`infra/deploy.sh` now runs these steps in order on every push to `main`:

1. Build the images. The running containers are untouched.
2. Back up the database with a compressed `pg_dump` to `/root/backups/deploy-<time>-<previous commit>.sql.gz`, checked with `gzip -t`. The newest 20 backups are kept.
3. Apply migrations: `alembic upgrade head` in the `migrate` container, as the database owner. Postgres DDL is transactional, so a failing migration rolls back completely.
4. Restart the containers with the new images.

If step 2 or 3 fails, the deploy stops there. The old containers keep running on the old schema, and the GitHub Actions run shows the failure.

## Rules this depends on

- **Migrations must be backward compatible for one deploy.** Old code runs for a few seconds against the new schema. Add columns and tables freely. To rename or drop, use two PRs: stop using the column first, then remove it.
- **Destructive migrations** (dropping data, rewriting rows) still need Alireza's explicit approval in the PR before merge. CI's downgrade/upgrade round-trip does not replace that review.
- The API still connects only as `del_app`. The owner credentials exist only in the one-off `migrate` container.

## Consequences

- Merge means live. No manual database step after merging.
- Backups live on the same server, which protects against bad migrations but not against losing the server. Off-site backups and a restore drill remain a Phase 5 task.
