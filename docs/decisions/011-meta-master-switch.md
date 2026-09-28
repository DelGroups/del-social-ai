# 011 — Meta master switch

**Status:** accepted, 2026-09-28

## Context
On 2026-09-27 Meta flagged our developer account ("unusual activity") and answered every call with
"API access blocked." Retrying keeps the flag alive. The owner asked that no agent contact Meta at
all until he says so, so the block can reset.

## Decision
One server switch, `META_PAUSED=true` in the server `.env` (default false):
- `MetaClient` refuses every request (read, publish, token exchange) before any network call. It is
  the only path to Meta, so nothing can bypass it.
- The publishing scheduler does not start; approved posts keep their time and go out after the
  switch is turned off. "Publish now" answers 503 with a clear message.
- Research and competitor search run in web mode, without the "Meta blocked" alarm and without
  marking the connection as broken. Adding competitors by name answers that Meta is paused.
- The Team Lead sees `instagram_access: paused by the owner` and never suggests Meta actions.

Turning it back on: set `META_PAUSED=false` in `/opt/del-social-ai/.env` and restart the api service.
