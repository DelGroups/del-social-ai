"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/client-api";
import {
  LOCALE_COOKIE,
  LOCALE_LABELS,
  LOCALES,
  THEME_COOKIE,
  THEMES,
  type Locale,
  type Theme,
  setPrefCookie,
} from "@/lib/prefs";
import type { Membership } from "@/lib/types";

import { Button, Input, Select } from "./ui";

/** A one-time link with a copy button. */
export function CopyField({ value }: { value: string }) {
  const t = useTranslations("common");
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex gap-2">
      <Input readOnly value={value} onFocus={(e) => e.currentTarget.select()} />
      <Button
        type="button"
        variant="ghost"
        onClick={async () => {
          await navigator.clipboard.writeText(value);
          setCopied(true);
        }}
      >
        {copied ? t("copied") : t("copy")}
      </Button>
    </div>
  );
}

export function PreferencePickers({ locale, theme }: { locale: Locale; theme: Theme }) {
  const t = useTranslations();
  const router = useRouter();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        aria-label={t("common.language")}
        defaultValue={locale}
        onChange={(e) => {
          setPrefCookie(LOCALE_COOKIE, e.target.value);
          router.refresh();
        }}
      >
        {LOCALES.map((l) => (
          <option key={l} value={l}>
            {LOCALE_LABELS[l]}
          </option>
        ))}
      </Select>
      <Select
        aria-label={t("common.theme")}
        defaultValue={theme}
        onChange={(e) => {
          setPrefCookie(THEME_COOKIE, e.target.value);
          document.documentElement.dataset.theme = e.target.value;
        }}
      >
        {THEMES.map((th) => (
          <option key={th} value={th}>
            {t(`themes.${th}`)}
          </option>
        ))}
      </Select>
    </div>
  );
}

export function SignOutButton() {
  const t = useTranslations("common");
  const router = useRouter();
  return (
    <Button
      variant="ghost"
      onClick={async () => {
        await api("/auth/logout", { method: "POST" }).catch(() => undefined);
        router.push("/login");
        router.refresh();
      }}
    >
      {t("signOut")}
    </Button>
  );
}

export function TenantSwitcher({ memberships, current }: { memberships: Membership[]; current?: string }) {
  const t = useTranslations("tenant");
  const router = useRouter();
  if (memberships.length === 0) return null;
  return (
    <Select
      aria-label={t("switch")}
      value={current ?? ""}
      onChange={(e) => e.target.value && router.push(`/t/${e.target.value}`)}
    >
      {!current && <option value="">{t("switch")}</option>}
      {memberships.map((m) => (
        <option key={m.tenant_id} value={m.tenant_id}>
          {m.tenant_name}
        </option>
      ))}
    </Select>
  );
}
