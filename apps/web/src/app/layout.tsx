import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { Inter, JetBrains_Mono, Lora, Nunito } from "next/font/google";
import { cookies } from "next/headers";

import { DEFAULT_THEME, THEME_COOKIE, isTheme } from "@/lib/prefs";

import "./globals.css";

// One family per theme (ADR 010); all cover Azerbaijani (ə ş ğ ı) and Cyrillic. Only Inter is
// preloaded (the default theme); the others load when a theme uses them.
// (next/font needs each option written out literally)
const inter = Inter({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-inter" });
const lora = Lora({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-lora", preload: false });
const mono = JetBrains_Mono({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-mono", preload: false });
const nunito = Nunito({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-nunito", preload: false });

export const metadata: Metadata = {
  title: "DEL SOCIAL AI",
  description: "AI team for your social media",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const themeCookie = (await cookies()).get(THEME_COOKIE)?.value;
  const theme = isTheme(themeCookie) ? themeCookie : DEFAULT_THEME;
  return (
    <html lang={locale} data-theme={theme} className={`${inter.variable} ${lora.variable} ${mono.variable} ${nunito.variable}`}>
      <body className="font-sans antialiased">
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
