# ADR 008: The team works every day without being asked: market research and the Team Lead's report

- **Status:** Accepted. Alireza asked for this on 2026-09-27: "agents that check and analyse the target market every day and report and suggest to me and the Team Lead… the Team Lead should report to me every day, plan ahead, research and send me marketing suggestions".
- **Date:** 2026-09-27
- **Phase:** 1 (part of Phase 2 "Team Lead, Analyst" and Phase 3 "Researcher", pulled forward)

## Context

Until now the agents only reacted: nothing happened until the owner uploaded photos or wrote an instruction. The owner wants a team that works like employees. Each agent has a job, researches the market, reports every morning, and proposes the next steps.

## Decision

1. **Market Researcher, every day at 08:00 Baku.**
   - **Code collects the data** (`del_social/research/collect.py`):
     - competitors' public Instagram posts, through Meta **Business Discovery**. This is the official API: no scraping, and it works for business and creator accounts;
     - our own recent posts and their engagement;
     - customers' comments from the last 14 days, as text only, without names.

     All numbers are computed by code: posts per week, average likes and comments, engagement = (likes + comments) / followers, top posts.
   - **A web researcher** uses Anthropic's server-side web search. It is limited to 5 searches. No search location is sent: the API rejects Azerbaijan ("Country code AZ is not supported", found on the first real run), so the prompt names Baku and Azerbaijan instead. It writes plain-text notes with numbered sources. It is a separate call, so web content never reaches an agent that has tools.
   - **The Market Researcher** (Sonnet, with photos of the best competitor posts) writes a structured report:
     - findings, each with evidence and a confidence level;
     - post ideas with our real products (made-up product ids are dropped by code);
     - questions for the owner, and the data that was missing.
   - Captions, comments, web notes and images are labelled as untrusted data (CLAUDE.md principle 6).
2. **The Team Lead's morning report, every day at 09:00.**
   - Code counts what happened since yesterday: posts written, published, waiting and scheduled; photos not yet analysed; the package allowance left.
   - The Team Lead writes: what was done, what the market says, today's plan, up to 4 suggestions and up to 2 questions.
   - A suggestion is either "a post with this product" or nothing. Code checks that the product exists and has photos. **Nothing starts until the owner presses "Prepare it"**, and even then the usual wizard (Copywriter → Brand Guardian → approval) runs, within the package.
3. **Each report is made once.** Reports are claimed in `daily_reports`, unique per company, kind and Baku day, before any work starts. Owners and admins can make one again from the panel ("Research the market now" / "Morning report now").
4. **Who gets it.** Every company with an active, unexpired package, found by `daily_tenants()`, a SECURITY DEFINER function that returns only ids. Each switch can be turned off in Brand profile → Market, which also holds:
   - the competitors' Instagram accounts, websites and search words;
   - the report language: az, ru, en or fa.
5. **Panel.**
   - A **Team** page shows each agent's role, duties, schedule, who it reports to and what it is doing now, plus the agents joining next.
   - **Reports** lists the daily reports. The full market report shows the findings, the numbers table computed by code, customer comments and web sources.
   - The reports appear as cards in the Team Room.
   - The Team Lead also sees the latest market report when the owner chats with it.

## Cost

These are estimates to be confirmed on the first real runs:
- market research: about $0.10–0.20 a day (tokens, 6 small images, up to 5 searches at $0.01 each);
- morning report: about $0.03 a day.

That is roughly $4–7 a month per company. It is recorded per agent in `llm_calls`. Search requests are priced by code, in `pricing.WEB_SEARCH`.

## Consequences

- There is a second background loop in the API process (`team.daily.loop`, every 5 minutes), next to the publishing scheduler. Both can move to the arq worker later without changes elsewhere.
- Web search must be allowed for the Anthropic organization. If it is not, the report is still made, and it says that the web part is missing.
- The Team Lead can start the research or its report at once from the chat (actions `run_market_research`, `morning_report`, prompt v2), for example when the owner has just added competitors.
- Competitors with personal (non-business) Instagram accounts are not visible through Business Discovery. The report says so for each one.
