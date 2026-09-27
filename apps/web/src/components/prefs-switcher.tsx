"use client";

// Language and theme at the bottom of the menu: three small language tabs, and one theme button
// that opens a short list. Each theme in the list is shown as a tiny window of that theme.
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { LOCALES, LOCALE_COOKIE, type Locale, THEMES, THEME_COOKIE, type Theme, setPrefCookie } from "@/lib/prefs";

// What each theme looks like, for its preview (mirrors globals.css)
const LOOK: Record<Theme, { bg: string; surface: string; text: string; accent: string; radius: number; glow?: string }> = {
  midnight: { bg: "#0b1422", surface: "#121e30", text: "#e8edf5", accent: "#ff7a1a", radius: 6 },
  graphite: { bg: "#0d0a19", surface: "#1c1730", text: "#ece9f7", accent: "#8b7cff", radius: 7, glow: "#8b7cff" },
  daylight: { bg: "#f3f4f7", surface: "#ffffff", text: "#111827", accent: "#2563eb", radius: 5 },
  sage: { bg: "#e8eee7", surface: "#f7f9f5", text: "#22302a", accent: "#3e8e6e", radius: 10 },
};

function Preview({ theme, size = "md" }: { theme: Theme; size?: "sm" | "md" }) {
  const l = LOOK[theme];
  const w = size === "sm" ? 22 : 44;
  const h = size === "sm" ? 16 : 30;
  return (
    <span
      aria-hidden="true"
      className="relative block shrink-0 overflow-hidden"
      style={{ width: w, height: h, background: l.bg, borderRadius: size === "sm" ? 5 : l.radius, boxShadow: "inset 0 0 0 1px rgb(128 128 128 / 0.25)" }}
    >
      {size === "md" && (
        <>
          <span className="absolute left-1.5 top-1.5 block h-3.5 w-6" style={{ background: l.surface, borderRadius: l.radius / 2 }} />
          <span className="absolute left-2.5 top-2.5 block h-[2px] w-3.5" style={{ background: l.text, opacity: 0.6, borderRadius: 2 }} />
        </>
      )}
      <span
        className="absolute block rounded-full"
        style={{
          width: size === "sm" ? 6 : 8, height: size === "sm" ? 6 : 8, right: size === "sm" ? 3 : 5, bottom: size === "sm" ? 3 : 5,
          background: l.accent, boxShadow: l.glow ? `0 0 8px ${l.glow}` : undefined,
        }}
      />
    </span>
  );
}

export function PrefsSwitcher({ locale, theme: initial, compact = false }: { locale: string; theme: string; compact?: boolean }) {
  const t = useTranslations();
  const router = useRouter();
  const [theme, setTheme] = useState<Theme>((THEMES as readonly string[]).includes(initial) ? (initial as Theme) : "midnight");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  function pickTheme(th: Theme) {
    setPrefCookie(THEME_COOKIE, th);
    document.documentElement.dataset.theme = th; // instant: the fonts are already there
    setTheme(th);
    setOpen(false);
  }
  function pickLocale(l: Locale) {
    if (l === locale) return;
    setPrefCookie(LOCALE_COOKIE, l);
    router.refresh();
  }

  return (
    <div ref={box} className="relative flex items-center gap-2">
      <div className="flex rounded-md bg-bg p-0.5 text-[11px] font-semibold" role="group" aria-label={t("common.language")}>
        {LOCALES.map((l) => (
          <button
            key={l}
            type="button"
            onClick={() => pickLocale(l)}
            aria-pressed={l === locale}
            className={`rounded px-2 py-1 uppercase transition ${l === locale ? "bg-surface text-text" : "text-muted hover:text-text"}`}
          >
            {l}
          </button>
        ))}
      </div>

      <div className={compact ? "relative" : "min-w-0 flex-1"}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={t("common.theme")}
          className="flex w-full items-center gap-2 rounded-md bg-bg px-2 py-1 text-xs text-muted transition hover:text-text"
        >
          <Preview theme={theme} size="sm" />
          <span className="min-w-0 flex-1 truncate text-left">{t(`themes.${theme}`)}</span>
          <svg viewBox="0 0 20 20" className={`h-3.5 w-3.5 shrink-0 transition ${open ? "rotate-180" : ""}`} fill="currentColor" aria-hidden="true">
            <path d="M5.2 7.7a.75.75 0 0 1 1.06.02L10 11.6l3.74-3.88a.75.75 0 1 1 1.08 1.04l-4.28 4.44a.75.75 0 0 1-1.08 0L5.18 8.76a.75.75 0 0 1 .02-1.06" />
          </svg>
        </button>

        {open && (
          <ul
            role="listbox"
            aria-label={t("common.theme")}
            className={`absolute z-50 space-y-0.5 rounded-xl border border-border bg-surface p-1.5 ${compact ? "right-0 top-full mt-2 w-60" : "inset-x-0 bottom-full mb-2"}`}
            style={{ boxShadow: "0 18px 40px -12px rgb(0 0 0 / 0.35)" }}
          >
            {THEMES.map((th) => (
              <li key={th}>
                <button
                  type="button"
                  role="option"
                  aria-selected={th === theme}
                  onClick={() => pickTheme(th)}
                  className={`flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left transition ${th === theme ? "bg-bg" : "hover:bg-bg"}`}
                >
                  <Preview theme={th} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-text">{t(`themes.${th}`)}</span>
                    <span className="block truncate text-[11px] text-muted">{t(`themeHints.${th}`)}</span>
                  </span>
                  {th === theme && (
                    <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-accent" fill="currentColor" aria-hidden="true">
                      <path d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0L3.3 9.7a1 1 0 1 1 1.4-1.4l3.8 3.8 6.8-6.8a1 1 0 0 1 1.4 0" />
                    </svg>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
