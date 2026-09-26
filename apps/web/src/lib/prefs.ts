// Per-browser preferences kept in cookies so the server renders the right language/theme (no flash).
export const LOCALES = ["az", "ru", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "az";
export const LOCALE_COOKIE = "NEXT_LOCALE";
export const LOCALE_LABELS: Record<Locale, string> = { az: "Azərbaycan", ru: "Русский", en: "English" };

export const THEMES = ["midnight", "daylight", "graphite", "sage"] as const;
export type Theme = (typeof THEMES)[number];
export const DEFAULT_THEME: Theme = "midnight";
export const THEME_COOKIE = "theme";

export const isLocale = (v: string | undefined): v is Locale => LOCALES.includes(v as Locale);
export const isTheme = (v: string | undefined): v is Theme => THEMES.includes(v as Theme);

export function setPrefCookie(name: string, value: string) {
  document.cookie = `${name}=${value}; path=/; max-age=31536000; samesite=lax`;
}

// dd.mm.yyyy (and HH:MM) in Baku time. Node's built-in ICU lacks full Azerbaijani data
// ("2026 M09 26"), and a fixed zone keeps server and browser output identical.
const DATE = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Baku", day: "2-digit", month: "2-digit", year: "numeric" });
const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Baku", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
});
export const formatDate = (iso: string) => DATE.format(new Date(iso)).replaceAll("/", ".");
export const formatDateTime = (iso: string) => DATE_TIME.format(new Date(iso)).replaceAll("/", ".").replace(",", "");
