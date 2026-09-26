# Phase 1 plan — Vertical slice on Del Furniture

- **Status:** Draft for Alireza's review
- **Date:** 2026-09-26
- **Done when (CLAUDE.md):** ≥ 80% of eval outputs are publishable without edits, and one real post is published through the system.

## 1. What Phase 1 delivers

One complete path, end to end, for one tenant (Del Furniture):

```
Brand profile ──► Social Media Manager: weekly plan (slots)
                        │ one brief per slot
                        ▼
                  Copywriter: 3 options ──► Brand Guardian ──fix (max 2 loops)──┐
                        ▲                        │ pass                          │
                        └────────────────────────┼───────────────────────────────┘
                                                 ▼
                         Approval (panel queue + Telegram): pick 1 of 3 / edit / reject
                                                 ▼
                         Scheduler (code picks exact time) ──► Publish tool ──► Instagram / Facebook
```

**Out of scope** (later phases): Team Lead, image generation and text overlay (Visual Designer), comments/DMs, analytics reports, Sales, video. Anything new that comes up goes on the Phase 2 list.

## 2. Brand profile (the input every agent reads)

This is one versioned document per tenant. Editing it creates a new version, and every generated post records which version it used.

| Section | Contents (Del Furniture examples) |
|---|---|
| Basics | Company name, what it sells, cities served, showroom address, working hours, website, phone/WhatsApp |
| Audience | Who buys (for example new apartment owners, families, offices, designers), what they care about |
| Products | Categories (living room, bedroom, kitchen, office, custom), materials, what makes them different (USPs) |
| Voice | Tone words (for example warm, confident, simple), formality (`siz` / `вы`), emoji policy, caption length |
| Languages | Per channel: Azerbaijani only / Russian only / both, and how both are combined |
| Never list | Words, claims and topics never to use (competitor names, "cheapest", unverifiable claims, politics, religion…) |
| Claims | Allowed claims with proof (for example "10-year warranty" only if true) |
| Prices | Phase 1: posts never mention prices or discounts unless a human writes them in the brief |
| CTAs | Allowed calls to action and contact lines |
| Hashtags | Branded tags plus an approved pool; max per post |
| Examples | 5–10 past posts the owner likes (and optionally ones they dislike) |
| Occasions | Dates the brand marks (Novruz, Yeni il, 8 Mart, Ramazan/Qurban bayramı, Black Friday, school season) |

**Onboarding.** A form in the panel with sensible defaults. There is an optional "draft from our Instagram" button: it reads the last 30 captions via the Graph API, an LLM drafts the Voice/Hashtags/Examples sections, and the owner edits and approves. The captions are treated as untrusted data.

## 3. Photos (Instagram needs an image or video to publish)

Image generation is Phase 2. In Phase 1:

- The panel has a **media library**: the team uploads real product and showroom photos, tagged by category.
- For each slot, the Social Media Manager picks candidate photos by tag. The approver can swap the photo in the approval step.
- The files live on the server volume. Meta fetches them from a short-lived signed URL at `api.del-groups.com/media/...`.
- No text is drawn on photos in Phase 1.

## 4. Agents in this phase

Each agent has a versioned prompt file, a Pydantic output schema, a tool allowlist and eval cases (CLAUDE.md working rules).

| Agent | Model | Output | Tools |
|---|---|---|---|
| Social Media Manager | Opus (weekly plan) | Slots: date window, channel(s), format (post/carousel), goal, language, brief, photo tags | read brand profile, read media library tags, read occasions calendar |
| Copywriter | Sonnet | 3 distinct options: caption (az/ru), CTA, hashtags, alt text, and the angle of each | read brand profile |
| Brand Guardian | Haiku, then Sonnet on borderline cases | Per option: pass / fix (notes) / block, with the rule that triggered it | read brand profile, deterministic checks (length limits, hashtag count, banned words, price/number detector) |

Every agent can also return a `question` instead of an answer. The graph then pauses and the question goes to the panel/Telegram.

## 5. Orchestration

- **LangGraph with the Postgres checkpointer.** A run pauses at the approval step (an interrupt) and resumes when someone approves, even days later and across server restarts.
- **Graph edges are fixed in code.** Agents never call each other.
- The Guardian → Copywriter fix loop runs at most 2 times. After that, the slot goes to the human with the Guardian's notes.
- The **exact** publish time is computed by code: the plan's time window, the tenant's quiet hours, and default best times per channel. The LLM never outputs a timestamp that gets used directly.

## 6. Approval

- **Panel queue:** each slot shows 3 options side by side with the photo, the Guardian's verdict and the scheduled time. Actions: approve option N, edit then approve, reject with a reason, regenerate.
- **Telegram:** a bot in an approval group posts a preview with buttons ✅1 ✅2 ✅3 / ✏️ (opens the panel) / ❌. Only members with the `approver` role or higher can act. Telegram users are linked to panel accounts once, with a one-time code.
- Every decision and its reason is stored. This feeds the rejection-rate metric and later the voice profile.
- **Default autonomy = manual approval.** Nothing is published without a human.

## 7. Publishing

- The worker runs on Redis + arq; a job fires at the scheduled time.
- **Instagram:** create a media container from the signed photo URL, wait until it is ready, then publish. **Facebook:** a page photo post.
- **Idempotent:** a post is never published twice, even on retry. Every attempt is stored with Meta's response.
- A failure is shown in the panel and sent to Telegram. There is no silent retry beyond 3 attempts.
- **Before the first real post, Alireza confirms explicitly.**

## 8. New tables (each: migration + RLS + isolation test)

- `brand_profiles`: versioned (`tenant_id`, `version`, `data` jsonb, `created_by`, `approved_at`)
- `media_assets`: file path, tags, width/height, uploaded_by
- `content_plans`, `content_slots`: the weekly plan and its slots
- `content_options`: 3 per slot, with the Guardian verdict per option
- `approval_decisions`: who, what, reason, and via panel or Telegram
- `scheduled_posts`, `publish_attempts`
- `llm_calls`: tenant, agent, model, prompt version, tokens, cost, latency, Langfuse trace id
- LangGraph checkpoint tables, created by the library and protected by the same RLS approach

## 9. Tracing and cost

- Every LLM call goes through one wrapper. It sends the trace to Langfuse and writes a row to `llm_calls`.
- **Rough cost for Del Furniture:** a weekly plan plus about 5–7 slots × 3 options plus Guardian checks is on the order of a few US dollars per month. This will be measured from `llm_calls` after the first week.

## 10. Evals (the Phase 1 done criterion)

- `evals/copywriter/`: 40 briefs covering products, occasions, both languages, tricky cases (price requests, sensitive dates, competitor mentions).
- A runner script generates options for every brief and puts them in a review page in the panel.
- **Alireza marks each option: publishable as-is / needs edits / wrong.** Target: ≥ 80% of briefs have at least one option that is publishable as-is.
- Guardian evals: 20 deliberately bad captions (banned words, invented prices, wrong language, too many hashtags) must all be caught.

## 11. Order of work (each step is a PR, tested, then merged)

1. **Brand profile:** table, API, panel form, versioning. Alireza fills it in for Del Furniture.
2. **LLM layer:** Anthropic client wrapper, prompt files, Langfuse and cost logging, eval runner.
3. **Copywriter + Brand Guardian + evals:** first quality check by Alireza before anything else is built on top.
4. **Media library:** upload and tag photos, signed media URLs.
5. **Social Media Manager + graph + approval queue in the panel.**
6. **Telegram approval bot.**
7. **Scheduler + publishing to Instagram/Facebook,** then the first real post after explicit confirmation.

## 12. What Alireza needs to provide

- **Anthropic API key, Langfuse keys, Telegram bot token.** He enters them on the server himself, never in chat.
- The brand profile answers (form in step 1).
- 20–50 good product/showroom photos.
- Review of the eval outputs in step 3.
