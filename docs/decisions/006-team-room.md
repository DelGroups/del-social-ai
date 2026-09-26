# ADR 006: Team Room — work starts from one instruction

- **Status:** Accepted. Alireza approved the prototype on 2026-09-27 ("wizard process; the agent asks for approval, the user only gives correction instructions when needed").
- **Date:** 2026-09-27
- **Phase:** 1 (pulls forward the Phase 2 Team Lead and part of the Phase 3 panel)

## Context

The panel had become a manual post builder: the user picked photos, pressed generate, edited text and pressed publish. Alireza wants the agents to act like employees. He gives one instruction, they do the work, and he only approves or asks for a change.

## Decision

1. **The home page is the Team Room.** It shows the chat with the Team Lead, a live team diagram, agents' current work, and posts waiting for approval, scheduled or published. It also shows today's and this month's AI cost, and connections. The panel polls every 3 s. Websockets can come later if needed.
2. **The Team Lead only chooses from a fixed menu.** Its output is a reply plus actions from a fixed menu: `create_post`, `revise_post`, `analyze_photos`. Code checks every id against the tenant's data and runs the action. An id the model invents is refused with a note in the chat. A viewer can talk to the Team Lead but cannot start work.
3. **Publish times are computed by code.** The model picks a named slot (`today_evening`, `tomorrow_morning`, `specific` date + time) and `team/timing.py` resolves it in Baku time (UTC+4). The defaults are 10:00 and 19:00. Dates in the past or more than 6 months ahead are refused.
4. **Each task is a wizard with fixed steps:** photos → copy → brand check → **your approval** → publish. The graph always stops at approval, because the default autonomy policy is human approval.
5. **Approving** schedules the post if it has a future time; otherwise the post is published now. Both need an explicit confirmation. A scheduler loop in the API publishes due posts. It claims each post atomically (`scheduled → publishing`) through the SECURITY DEFINER function `due_scheduled_posts()`, so a post is never published twice.
6. **Changes are given in words.** "Ask for a change" sends the instruction to the Copywriter. The Copywriter rewrites the text and the Brand Guardian checks it again before the post returns for approval. Manual editing stays available under "Details".
7. **Navigation:** Team, Approvals, Posts, Photos, Reports, Settings. Settings groups Brand, Connections, Members and Agent tests.

## Consequences

- New tables `tasks`, `chat_messages` and `agent_events` each have RLS and are covered by the isolation tests.
- Every agent step writes an event, and the live view is built from these events. That makes it cheap to show what each agent is doing.
- The Reports page is a first version: published posts and AI cost. Reach and engagement analytics, competitor research and PDF export come with the Analyst agent.
- Telegram approval (step 6) will reuse the same `/approve` and `/revise` paths.
