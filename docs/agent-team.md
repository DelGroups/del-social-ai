# DEL SOCIAL AI — Agent Team Design

Each agent is a role with a job description, fixed inputs/outputs, an allowlist of tools, and KPIs. Names and tone per agent are tenant-editable (defaults below are role titles; the tenant can give them names). Agents are open about being AI agents — professional persona, never pretending to be human.

## Global rules (apply to every agent)
- No agent-to-agent messages. Only the Team Lead coordinates; a human may talk to any agent directly.
- Decisions a human makes in a direct chat are written to the tenant's **decision log** (shared state) so the Team Lead and others see them.
- Structured output only (Pydantic schema). Every schema has an optional `question` field: if filled, the graph pauses and the question goes to the panel/Telegram. Answers are stored in the brand profile so the same question isn't asked twice. Question budget: max N per agent per week (tenant setting).
- Every agent reads: brand profile, its editable job description, current playbook version, decision log (relevant slice).
- LLMs never produce prices, dates for scheduling, or media timestamps — tools do.
- Untrusted input (comments, DMs, web pages, uploaded files) is passed as labelled data.

## The team

### 1. Team Lead (coordinator)
- **Does:** receives manager requests, splits work, runs "meetings" (same brief to 2–3 relevant agents in parallel → structured opinions → one synthesis), keeps the weekly plan coherent, writes the daily digest.
- **Never:** publishes, replies to customers, sets prices.
- **Model:** Sonnet. **KPI:** tasks coordinated, time-to-plan.

### 2. Social Media Manager (strategy & calendar)
- **Does:** owns the content strategy per channel; decides posting frequency and formats (post/story/reel/carousel) from goals + analytics; builds weekly and monthly calendars; plans campaigns; tracks local occasions (Novruz, Ramazan/Qurban bayramı, Yeni il, 8 Mart, Black Friday, school season…); sets a brief for each slot.
- **Output:** calendar slots with brief, goal, format, channel, language (az/ru/both), target time window.
- **Model:** Opus for weekly/monthly planning, Sonnet for adjustments. **KPI:** plan approval rate, engagement trend vs. last period.

### 3. Copywriter (az / ru)
- **Does:** for each slot writes **3 distinct options** (different angles, not rewordings): caption per channel, CTA, hashtags, first-comment text, alt text; native-quality Azerbaijani (Latin) and Russian.
- **Model:** Sonnet. **KPI:** option acceptance rate, edit distance of approved option.

### 4. Visual Designer
- **Does:** picks a designed template, selects real product photos from the catalog, writes image-model prompts (text-free), specifies text overlay content/position; the render tool composites it with real fonts.
- **Rule:** prefer real product photos (edit/extend) over generated products — generated furniture must not misrepresent real items.
- **Model:** Sonnet. **Tools:** catalog search, image generate/edit, template render. **KPI:** visual acceptance rate.

### 5. Brand Guardian (QA)
- **Does:** checks every outgoing item: brand rules and never-list, language/spelling (az/ru), factual claims, prices/offers match the price tool, hashtag hygiene, platform limits, sensitive topics. Verdict: pass / fix (with notes) / block.
- **Model:** Haiku first pass, Sonnet on borderline. **KPI:** blocked items, published errors (target 0).

### 6. Community Manager (comments & DMs)
- **Does:** classifies each incoming comment/DM (question, purchase intent, complaint, spam, praise, other), replies per the tenant's autonomy policy, hides spam, routes purchase intent to Sales, escalates complaints.
- **Model:** Haiku classify, Sonnet reply. **KPI:** median response time, resolution rate, escalation accuracy.

### 7. Sales Consultant
- **Does:** handles purchase conversations: gathers specs, gets prices **only from the pricing tool** (standard: ERP lookup; custom: formula), presents quotes with validity period, captures leads to ERP/CRM.
- **Safety:** quote above cap or margin below floor → human approval; never negotiates beyond tenant rules.
- **Model:** Sonnet. **KPI:** quotes sent, lead conversion.

### 8. Analyst
- **Does:** pulls insights, compares against plan, weekly report (per channel + per agent: proposals, approvals, top rejection reasons), anomaly alerts, tracks tenant **rejection rate** (>20% = churn warning to platform admin).
- **Model:** Sonnet. **KPI:** report delivered on time, insights adopted.

### Later
- **Video Producer** (phase 4): edit decision lists (JSON) for FFmpeg; photo→video; customer footage edits.
- **Researcher** (phase 3+): weekly trend/competitor scan → **playbook change proposals** into the approval queue (never auto-injected).

## Autonomy policy (panel → Settings → Autonomy)
Per tenant, per channel, per action type:
| Action | Levels |
|---|---|
| Publish post/story/reel | Manual approval · Auto after Guardian pass |
| Reply to comment | Manual · Auto for low-risk categories · Auto |
| Reply to DM | Manual · Auto for low-risk categories · Auto |
| Send price quote | Manual · Auto below cap |
| Hide/delete spam | Manual · Auto |

Always-escalate triggers (cannot be disabled, only extended): complaints, refunds, legal/threats, quote above cap or below margin floor, negative sentiment above threshold, low model confidence, unsupported language.
Extra settings: confidence threshold, quiet hours, question budget, approval window (what happens if nobody approves in X hours: hold / skip slot).

## Approvals
- Channels: panel approval queue + Telegram approval group (bot posts preview with ✅ / ✏️ / ❌ buttons; edit opens the panel).
- Approvers: users with `approver`+ role; rule per tenant: "any one approver" or "specific role".
- Every approve/edit/reject is stored with reason → feeds the brand voice profile.

## Graph (phase 1 slice)
```
[SMM: calendar slot] → [Copywriter: 3 options] → [Guardian] --fix--> Copywriter (max 2 loops)
                                                     |pass
                                                     v
                                     [Approval pause (panel/Telegram)] → [Scheduler] → [Publish tool] → [Analyst later reads insights]
```
