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
