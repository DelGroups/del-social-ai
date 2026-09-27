"use client";

// Language and theme, one click each, at the bottom of the menu. Each theme swatch is a tiny preview
// of that theme: its background, its accent and "Aa" in its own font and corner shape.
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { LOCALES, LOCALE_COOKIE, type Locale, THEMES, THEME_COOKIE, type Theme, setPrefCookie } from "@/lib/prefs";

const PREVIEW: Record<Theme, { bg: string; fg: string; accent: string; font: string; radius: number; border: string }> = {
  midnight: { bg: "#0b1422", fg: "#e8edf5", accent: "#ff7a1a", font: "var(--font-inter)", radius: 8, border: "solid" },
  daylight: { bg: "#f4f0e6", fg: "#1b1a17", accent: "#c8401e", font: "var(--font-lora)", radius: 2, border: "solid" },
  graphite: { bg: "#0a0b09", fg: "#b8f34a", accent: "#b8f34a", font: "var(--font-mono)", radius: 0, border: "dashed" },
  sage: { bg: "#e8eee7", fg: "#22302a", accent: "#3e8e6e", font: "var(--font-nunito)", radius: 14, border: "solid" },
};

export function PrefsSwitcher({ locale, theme: initial, compact = false }: { locale: string; theme: string; compact?: boolean }) {
  const t = useTranslations();
  const router = useRouter();
  const [theme, setTheme] = useState(initial);

  function pickTheme(th: Theme) {
    setPrefCookie(THEME_COOKIE, th);
    document.documentElement.dataset.theme = th; // instant: every font is already loaded
    setTheme(th);
  }
  function pickLocale(l: Locale) {
    if (l === locale) return;
    setPrefCookie(LOCALE_COOKIE, l);
    router.refresh();
  }

  return (
    <div className={compact ? "flex items-center gap-3" : "space-y-2"}>
      <div className={`flex overflow-hidden rounded-md border border-border text-[11px] font-semibold ${compact ? "" : "w-full"}`} role="group" aria-label={t("common.language")}>
        {LOCALES.map((l) => (
          <button
            key={l}
            type="button"
            onClick={() => pickLocale(l)}
            aria-pressed={l === locale}
            className={`px-2 py-1 uppercase transition ${compact ? "" : "flex-1"} ${l === locale ? "bg-accent text-accent-text" : "text-muted hover:text-text"}`}
            style={l === locale ? { boxShadow: "none", borderRadius: 0 } : undefined}
          >
            {l}
          </button>
        ))}
      </div>
      <div className={`flex items-center gap-1.5 ${compact ? "" : "justify-between"}`} role="group" aria-label={t("common.theme")}>
        {THEMES.map((th) => {
          const p = PREVIEW[th];
          const active = th === theme;
          return (
            <button
              key={th}
              type="button"
              onClick={() => pickTheme(th)}
              aria-pressed={active}
              title={t(`themes.${th}`)}
              aria-label={t(`themes.${th}`)}
              className={`relative grid h-7 place-items-center text-[11px] leading-none transition hover:scale-105 ${compact ? "w-8" : "flex-1"}`}
              style={{
                background: p.bg, color: p.fg, fontFamily: p.font, borderRadius: p.radius, textTransform: "none", letterSpacing: 0,
                border: `1px ${p.border} ${active ? p.accent : "rgb(128 128 128 / 0.35)"}`,
                boxShadow: active ? `0 0 0 2px var(--bg), 0 0 0 3px ${p.accent}` : "none",
              }}
            >
              Aa
              <span className="absolute bottom-0.5 right-0.5 h-1.5 w-1.5" style={{ background: p.accent, borderRadius: p.radius ? 99 : 0 }} />
            </button>
          );
        })}
      </div>
    </div>
  );
}
