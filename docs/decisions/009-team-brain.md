# ADR 009: The team thinks: it finds competitors, holds meetings and proposes goals

- **Status:** Accepted. Alireza asked for this on 2026-09-27: "the team must watch the market every day, find new competitors and add them itself… the system must be automated and above all intelligent: agents should think, the Team Lead should orchestrate and plan, talk to the agents himself, set goals and discuss with me what must improve, not just add posts."
- **Date:** 2026-09-27
- **Builds on:** ADR 008 (daily work), CLAUDE.md principle 1 (agents never talk to each other directly; coordination goes through the Team Lead; a meeting = parallel opinions + one synthesis)

## Decision

1. **Competitors are the team's own knowledge** (the `competitors` table).
   - The owner's list from the brand profile is merged in.
   - Every morning, code checks each account through Meta Business Discovery and marks it active, invalid (not visible: wrong username or a personal account) or inactive (no post for 90 days).
   - The web researcher (prompt v2) also lists the Instagram usernames it saw on the pages it read, and looks for the correct usernames of the invalid ones.
   - **Code verifies each candidate.** It is added (source "discovered") only if Meta shows a business account that posted in the last 90 days, has at least 200 followers and belongs to the market. "Belongs to the market" means its name or captions contain the brand's category or keyword words. At most 5 are added per day.
   - The owner can stop watching any account.
2. **Team meeting** (`team.meeting`). It runs every Friday at 09:30 (the weekly plan the owner asked for). The owner can also call one with a button, and the Team Lead can call one from the chat (action `team_meeting`, prompt v3).
   - The Team Lead reads the pack and asks each member one question: the Market Researcher, the Copywriter and the Brand Guardian. The pack is prepared by code: metrics, goals, the last week, the market report, competitors, products, the package.
   - The members answer in parallel, each from its role.
   - The Team Lead decides. This uses Opus, the strategy tier in CLAUDE.md. The decision contains a summary, decisions, up to 3 goals, a week plan, improvements beyond posting, and questions.
   - It is shown live as a fan-out/fan-in workflow.
3. **Goals are measured by code** (`team.metrics`): followers, engagement rate, average likes and comments (from the daily Instagram data), and posts per week (from our posts).
   - A proposed target must beat the current value and be at most 3 times it, or it is dropped.
   - The owner accepts or declines each goal. On acceptance, the baseline is measured again.
   - Progress is updated every morning; a goal becomes achieved or missed automatically.
   - The Team Lead reports on goals in the morning report (prompt v2) and sees them in the chat.
4. **Week plan.** One click prepares every plan item that has a real product with photos, scheduled for its day at 19:00 Baku. Each post still passes the usual wizard and the owner's approval, and the package quota applies.

## Consequences

- The meeting costs about $0.30 (three Sonnet answers and one Opus decision). Weekly, that is about $1.20 a month per company.
- `activity.step` now locks the task row, because members finish at the same moment. Without the lock, updates were lost; a test found this.
- Tables `competitors` and `goals` are tenant-scoped with forced RLS and covered by the isolation tests. Migration 0017.

## Revision (2026-09-27): the Team Lead can manage competitors

Alireza asked the Team Lead in the chat to "search for all our competitors in the Azerbaijani market and add them to your list". It answered that this was not possible and that he had to do it in the settings. The team had no tool for it.

- **New tool `find_competitors`.** A web search dedicated to competitors' Instagram accounts (prompt `competitor_finder`, up to 8 searches, about $0.10–0.15). Profile links (instagram.com/name) count as well as @names.
  - Code verifies every account the same way as in the daily research, adding up to 15 per search.
  - A wrong username the owner gave is replaced when the team finds the same company under its real username, for example `embawood.az` → `@embawood_mebel`.
  - Shown live as a three-step workflow.
- **New tool `add_competitors`.** Usernames the owner gives in the chat are checked on Instagram and watched.
- **Team Lead prompt v4.** It gets the list of what the team can and cannot do, so it doesn't refuse things the team can do. It also gets `<reply_language>`: the language of the owner's last message, detected by code. This language is binding, because in practice the model answered a Persian message in Azerbaijani.
