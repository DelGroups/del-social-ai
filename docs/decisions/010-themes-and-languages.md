# ADR 010: Themes with their own personality; the team speaks the owner's language

- **Status:** Accepted. Alireza asked on 2026-09-27:
  - "an easy but minimal place to change the theme; themes completely different from each other but all minimal; the theme affects everything: fonts, frames, buttons, colours, effects and type";
  - "the UI in three languages with easy switching";
  - "the Team Lead and the agents answer in whatever language I speak to them, but their social media work stays standard Azerbaijani and Russian".
- **Date:** 2026-09-27

## Decision

1. **Themes are full personalities**, all expressed as CSS tokens (`globals.css`).
   - What a theme sets:
     - colours;
     - body and heading fonts (weight, tracking, capitalisation);
     - the corner radius scale (Tailwind `rounded-*` reads it);
     - border style;
     - surface elevation;
     - the primary button style;
     - the workflow stage (`--stage-*`, `--flow`, `--node-*`).
   - The four themes:
     - Midnight: dark, Inter, soft glow.
     - Paper: editorial, serif headings, hairlines, flat.
     - Terminal: monospace, square, dashed, lime on black.
     - Soft: rounded type, pill buttons, floating surfaces.
   - The ids stay `midnight / daylight / graphite / sage`, so saved preferences still work.
   - All fonts are self-hosted by `next/font`. Only Inter is preloaded.
2. **Switching.**
   - Three language buttons (AZ RU EN) and four theme swatches sit at the bottom of the menu, and in the header on other pages.
   - Each swatch is a tiny preview: that theme's background, accent, and "Aa" in its font and shape.
   - The theme applies instantly (cookie plus `data-theme`). The language re-renders the page.
3. **The team's language.**
   - `texts.language_of()` decides it: the brand profile's report language if one is fixed, otherwise (**auto**, the new default) the language of the owner's latest chat message.
   - The language is detected by code from the script: Arabic script means Persian, Cyrillic means Russian. For Latin script, Azerbaijani letters and common words decide between Azerbaijani and English.
   - Every fixed message the team writes (events, chat notes, workflow step results, task titles) is a key in a four-language catalog (`team/texts.py`). It is rendered in that language when stored.
   - Reports, meetings and the morning report use the same language.
   - The Copywriter is unaffected: captions follow the brand's language mode (Azerbaijani + Russian).

## Consequences

- Messages are stored already rendered. Changing the language later does not translate old messages; this is simpler and matches a chat history.
- Error texts from quota and validation are still English. They are shown as they are for now.

## Revision (2026-09-27)

Alireza kept Midnight and Soft and rejected Paper and Terminal, as well as the "Aa" swatches.

- **Aurora** replaces Terminal: a deep violet night, glass cards, violet glow, Manrope.
- **Pearl** replaces Paper: clean white and cool grey, crisp blue, Manrope headings.
- Lora and JetBrains Mono are no longer loaded; Manrope is added. The ids stay (`graphite` = Aurora, `daylight` = Pearl), so saved choices still work.
- The picker is now one button showing the current theme. It opens a short list; each entry shows a tiny window of that theme, its name, and a one-line description.
