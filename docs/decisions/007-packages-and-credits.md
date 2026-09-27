# ADR 007: Packages, monthly allowance and credits

- **Status:** Accepted. Decided by Alireza on 2026-09-27.
- **Date:** 2026-09-27
- **Phase:** 1 (part of Phase 4 "credits and quotas" and Phase 5 "quotas, billing", pulled forward)
- **Source:** commercial proposal (proposal-tejari-final.pdf, 2026-09-20), §6 pricing model

## Context

Companies buy a package. The panel must show the package's allowance, how much of it is left, when it expires, and how to upgrade. It must never show our AI cost in dollars; that stays with the platform admin.

## Decision

1. **Plan catalog (`plans`).** A global, read-only table seeded from the proposal. NULL means unlimited.

   | Plan | Price | Posts/month | Channels | Users | Video credits/month | Features |
   |---|---|---|---|---|---|---|
   | Basic | 290 ₼ | 30 | 2 | 1 | 5 | — |
   | Pro | 690 ₼ | 90 ("unlimited" with a fair cap, decided by Alireza) | 4 | 5 | 15 | automatic replies, sales agent, weekly report |
   | Enterprise | from 1500 ₼ | unlimited | unlimited | unlimited | 30 | ERP and custom pricing |

   Video is sold as credits, not as a number of videos: photo → video costs 1 credit, editing the customer's footage 1, a full scenario video 10. A pack of 20 extra credits is recorded as `extra_video_credits`. Video usage stays at 0 until the video studio exists.
2. **Subscription.** One active subscription per company records the plan, a start date and an optional expiry. The monthly window runs from the start date (`subscription_period()`, a single SQL rule used everywhere).
3. **What counts, as Alireza decided:**
   - A post counts when it is **published**.
   - Approved posts waiting for their time are **reserved**. They count at approval, so they are always published, even after the package expires.
   - Rejected drafts are free, but drafts are capped at 3 × posts per month to prevent abuse.
4. **At the limit, new work stops and an upgrade is offered.** Code returns HTTP 402 with a code: `no_plan | expired | posts | drafts | channels | users`. The Team Lead repeats the message in the chat. A warning shows at 80% of the posts and 7 days before expiry. The check runs at these points:
   - starting a post, whether from the panel or the Team Lead;
   - approving or publishing;
   - connecting a new channel (reconnecting the same account is free);
   - inviting a user.
5. **Upgrades are manual until online payment (Phase 5).** An owner requests a package. The platform admin assigns it after payment, and the assignment starts a new monthly window. New companies get a package when they are created (default: Basic, 1 month). Companies that already existed were given Enterprise without an expiry.
6. **Dollar cost is for the platform admin only.** `platform_tenant_overview()` is a SECURITY DEFINER function that itself checks the caller is a platform admin. It returns only billing numbers: plan, usage counts, AI cost this month, and an estimated margin at 1 USD = 1.7 ₼. It returns no content. This is a deliberate, narrow exception to "platform admins see no tenant data" (ADR 002). The Team Room no longer returns any cost, and the Reports page shows no cost.

## Consequences

- New tables `subscriptions` and `plan_requests` are tenant-scoped with forced RLS and covered by the isolation tests. `plans` is readable by everyone and writable only through migrations.
- Changing prices or limits is a data change, not a code change. An edit screen for the platform admin can come later.
- Follow-up: `/tenants/{id}/usage` (dollar cost) is still reachable through the API by company owners and admins, although the panel no longer shows it. Restrict it before the first paying customer (Phase 5).
