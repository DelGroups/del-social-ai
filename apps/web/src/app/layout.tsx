import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { Inter } from "next/font/google";
import { cookies } from "next/headers";

import { DEFAULT_THEME, THEME_COOKIE, isTheme } from "@/lib/prefs";

import "./globals.css";

// Inter covers Azerbaijani (ə ş ğ ı) and Cyrillic
const inter = Inter({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "DEL SOCIAL AI",
  description: "AI team for your social media",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const themeCookie = (await cookies()).get(THEME_COOKIE)?.value;
  const theme = isTheme(themeCookie) ? themeCookie : DEFAULT_THEME;
  return (
    <html lang={locale} data-theme={theme} className={inter.variable}>
      <body className="font-sans antialiased">
        <NextIntlClientProvider>{children}</NextIntlClientProvider>
      </body>
    </html>
  );
}
