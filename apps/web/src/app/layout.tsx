import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { Inter, Manrope, Nunito, Vazirmatn } from "next/font/google";
import { cookies } from "next/headers";

import { DEFAULT_THEME, RTL_LOCALES, THEME_COOKIE, isTheme } from "@/lib/prefs";

import "./globals.css";

// One family per theme (ADR 010); all cover Azerbaijani (ə ş ğ ı) and Cyrillic. Only Inter is
// preloaded (the default theme); the others load when a theme uses them.
// (next/font needs each option written out literally)
const inter = Inter({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-inter" });
const manrope = Manrope({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-manrope", preload: false });
const nunito = Nunito({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-nunito", preload: false });
// Persian (preview): Vazirmatn, made for Persian and Arabic script
const vazirmatn = Vazirmatn({ subsets: ["arabic", "latin"], variable: "--font-vazirmatn", preload: false });

export const metadata: Metadata = {
  title: "DEL SOCIAL AI",
  description: "AI team for your social media",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const themeCookie = (await cookies()).get(THEME_COOKIE)?.value;
  const theme = isTheme(themeCookie) ? themeCookie : DEFAULT_THEME;
  return (
    <html lang={locale} dir={RTL_LOCALES.includes(locale) ? "rtl" : "ltr"} data-theme={theme}
      className={`${inter.variable} ${manrope.variable} ${nunito.variable} ${vazirmatn.variable}`}>
      <body className="font-sans antialiased">
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
