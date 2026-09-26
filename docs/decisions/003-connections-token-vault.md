# ADR 003: Channel connections and the token vault

- **Status:** Accepted
- **Date:** 2026-09-26
- **Phase:** 0
- **Builds on:** [ADR 001](001-multi-tenant-rls.md), [ADR 002](002-auth-accounts-memberships.md)

## Context

Each tenant connects its social accounts (Facebook pages, Instagram accounts, Telegram bots, later WhatsApp, TikTok, YouTube). A connection's access token can publish and message as the company, so it is the most sensitive data we hold. CLAUDE.md requires tokens to be encrypted at rest, never returned to the frontend and never logged.

## Decision

### Storage: one `connections` table, tenant-scoped

Columns: `channel`, `external_id` (page id / Instagram user id / bot id), `display_name`, `status` (`active` | `error`), `token_ciphertext`, `token_expires_at`, non-secret `details` (JSON), `last_checked_at`, `last_error`, `connected_by`. The table is unique per `(tenant_id, channel, external_id)`, so reconnecting the same account replaces its token instead of duplicating it. Forced RLS works as in ADR 001, and the isolation tests cover the table.

The unused `tenant_secrets` table from migration 0001 stays for now and will be removed in a later migration.

### Encryption: AES-256-GCM with a server-held key

- The key is `TOKEN_VAULT_KEY`: 32 random bytes, hex or base64. It lives only in the server's `.env`, never in the database, git or chat.
- Stored layout: `key version (1 byte) | nonce (12 random bytes) | ciphertext + tag`. The version byte lets us rotate keys later without guessing.
- **Associated data** is `del-social/connection/{tenant_id}/{connection_id}`. A ciphertext copied into another row or tenant fails authentication instead of decrypting, which is a second line of defence behind RLS.
- Encryption and decryption happen only in `connections/service.py`. API responses never include the token or its ciphertext; the tests assert this.
- Losing or changing the key makes the stored tokens unreadable. The Test button then says "connect again". Nothing else breaks.

### Channel adapters

Every channel implements the `ChannelAdapter` contract (`connections/base.py`): `check`, `refresh`, `publish`, `fetch_comments`, `reply_comment`, `fetch_messages`, `send_message`, `insights`, `capabilities`. Adapters receive decrypted `Credentials` from the service and never touch the database. Phase 0 implements connect + check for Telegram, Facebook and Instagram. Other methods raise `NotSupported` until the agents need them. WhatsApp, TikTok and YouTube are stubs marked "coming soon".

### Meta (Facebook + Instagram) OAuth

1. **Start** (`POST /tenants/{id}/connections/meta/start`, owner/admin only). A random `state` is stored in Redis for 10 minutes and bound to the account and the tenant. The browser goes to Facebook's dialog, which requests the scopes listed in `connections/meta.py` or uses `META_LOGIN_CONFIG_ID` for Facebook Login for Business.
2. **Callback** (`GET /connections/meta/callback`, reached via `app.del-groups.com/api/...`).
   - The state is single use (`GETDEL`).
   - The signed-in account must be the one that started the flow and must still hold `MANAGE_CONNECTIONS` in that tenant.
   - The code is exchanged server-side for a long-lived user token, and the pages list is read.
   - The page list, including page tokens, is encrypted with the vault and kept in Redis for 15 minutes.
   - The browser is redirected to the panel with only an opaque `pick` id.
3. **Pick.** The person chooses a page. We save the Facebook page and its linked Instagram professional account as two connections, both using the page token. Page tokens derived from a long-lived user token do not expire. The Redis entry is deleted after use.

All Graph calls send `appsecret_proof`. `META_APP_SECRET` is entered on the server only.

### Logging

- The Telegram bot token is part of Telegram's API URL. The `httpx` logger is therefore held at WARNING, and network errors are re-raised without httpx's message.
- The OAuth `code` may appear in access logs. It is single use, expires in minutes and is useless without the app secret, so it is acceptable.

## Consequences

- One Meta sign-in connects both Facebook and Instagram for a page.
- Phase 1 publishing reads a connection, gets credentials from the service and calls the adapter. No other code path can see a token.
- Key rotation: add a second key with version 2, re-encrypt rows in a one-off job, then retire version 1. We will build this when first needed.
