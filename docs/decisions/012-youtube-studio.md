# 012 — YouTube Studio (paid add-on)

**Status:** accepted, 2026-09-28 (prices are proposals until the owner confirms them)

## Context
Most YouTubers need help with the same things: a thumbnail for every video, titles, descriptions,
tags and chapters, knowing how the channel is doing, ideas that get views, and editing. The owner
wants a separate module for them: cheap to add, with credits that can be bought for more work, and
sellable on its own to a YouTuber who does not use the social media package. It should do
everything Google's APIs allow.

## Decision

### Selling it
- **Add-on** `youtube` ("YouTube Studio"): a monthly price with monthly credits included
  (proposal: 49 AZN, 100 credits). A company can have it with or without a social package.
- **Credits** pay for the expensive work (AI images, AI video, transcription, rendering, deep
  reviews). Monthly credits reset each period; bought credit packs never expire. Spending takes the
  monthly credits first. Every credit movement is a row in `credit_ledger`; balances are computed
  by code, never stored. Failed work is refunded automatically.
- Buying is a request the platform admin fulfils (no online payment until phase 5), like packages.
- A YouTube channel does not count against the social package's channel limit.

### Connecting
- Google OAuth (web server flow, offline access). The refresh token is kept in the token vault like
  every other token (ADR 003). Scopes: `youtube.force-ssl` (manage videos, thumbnails, captions,
  comments), `youtube.upload`, `yt-analytics.readonly`, `yt-analytics-monetary.readonly`.
- While the Google app is in "Testing" mode, Google expires refresh tokens after 7 days: the panel
  says so and asks to reconnect. Google verification of the app is needed before other companies
  use it (like Meta App Review, phase 5).
- The YouTube Data API has a daily unit budget per Google project (10,000 by default). Every call
  is counted by code; expensive calls (search: 100 units) are rationed, and we stop before the budget
  runs out rather than get the project blocked.

### What the module does (all numbers and timestamps by code, CLAUDE.md principle 2)
1. **Channel dashboard and reports**: subscribers, views, watch time, top videos, traffic sources,
   audiences and retention from the Analytics API; a report daily or every few hours (Telegram and
   panel). Recent-view deltas come from our own snapshots.
2. **Channel review**: a deep review with concrete advice (packaging, retention, consistency, topics,
   audience), by the strongest model, on demand or weekly.
3. **Ideas**: trending videos in the channel's field (YouTube's most popular chart, outliers among
   competitor channels: views compared with the channel's usual, computed by code) plus web research.
4. **Publishing kit per video**: three titles, description, tags, hashtags, pinned comment, chapters
   (timestamps taken from the transcript by code), translations of title and description, an SEO
   check by code; applied to YouTube with one click, with scheduling (`publishAt`).
5. **Thumbnail studio**: many options so the YouTuber reaches the result they want: background from a
   video frame, an upload or an AI image (always text-free), background removal for a cut-out subject,
   layouts, fonts that cover Azerbaijani and Cyrillic, colours, outline, glow, arrows and badges, and a
   preview as YouTube shows it. Text is always drawn by code (principle 8). Applied with one click.
6. **Comments**: reply drafts the owner approves before they are sent.
7. **Video lab**: uploads, transcription, silence cutting, subtitles (burned in or uploaded as
   captions), loudness normalisation, and Shorts cut from long videos (the model picks moments from the
   transcript; code turns them into times and renders with FFmpeg); AI video generation with a choice
   of models, durations and styles. Upload to YouTube from the panel.

### Not possible through Google's APIs
Thumbnail A/B testing ("Test & compare"), end screens, cards and Community posts: the module
prepares them and the YouTuber sets them in YouTube Studio. Custom thumbnails need a
phone-verified channel.

### Video lab (how it runs)
- Uploads arrive in 8 MB chunks (resumable), up to 4 GB and 90 minutes; lab files are deleted after
  14 days and each company has 12 GB of lab space (one small server disk is shared).
- FFmpeg runs niced and one job at a time for the whole server, so the panel and API stay fast.
- Transcription: Whisper on fal.ai, reached through a signed link that expires in two hours.
- AI video models are configuration (`VIDEO_MODELS_JSON`), with credits per second per model
  (proposal: fast 2, standard 4, premium with sound 9). Videos made with AI are uploaded to YouTube
  with its "altered or synthetic content" flag set, as YouTube's rules ask.
- Credits (proposal): transcription 1 per started 10 minutes; cutting, subtitles and exports 1 per
  started minute; Shorts 1 to choose the moments plus 1 per Short. A failed job refunds itself.
