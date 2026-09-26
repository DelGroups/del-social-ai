import { getLocale, getTranslations } from "next-intl/server";
import { cookies } from "next/headers";

import { PreferencePickers } from "@/components/client";
import { Shell } from "@/components/shell";
import { Card, PageTitle } from "@/components/ui";
import { DEFAULT_THEME, THEME_COOKIE, type Locale, isTheme } from "@/lib/prefs";
import { requireMe } from "@/lib/server-api";

import { PasswordForm } from "./password-form";

export default async function AccountPage() {
  const me = await requireMe("/account");
  const t = await getTranslations("account");
  const locale = (await getLocale()) as Locale;
  const themeCookie = (await cookies()).get(THEME_COOKIE)?.value;
  return (
    <Shell me={me}>
      <PageTitle>{t("title")}</PageTitle>
      <div className="grid gap-6 md:grid-cols-2">
        <Card title={t("changePassword")}>
          <p className="mb-4 text-sm text-muted">{me.email}</p>
          <PasswordForm />
        </Card>
        <Card title={t("preferences")}>
          <PreferencePickers locale={locale} theme={isTheme(themeCookie) ? themeCookie : DEFAULT_THEME} />
        </Card>
      </div>
    </Shell>
  );
}
