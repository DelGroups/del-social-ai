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

/** Password field with a show/hide toggle, so people can see exactly what they typed. */
export function PasswordInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const t = useTranslations("common");
  const [visible, setVisible] = useState(false);
  const label = visible ? t("hidePassword") : t("showPassword");
  return (
    <div className="relative">
      <Input {...props} type={visible ? "text" : "password"} className="pr-16" />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={label}
        title={label}
        className="absolute inset-y-0 right-0 px-3 text-xs text-muted hover:text-text"
      >
        {visible ? "\u25C9" : "\u25CE"}
      </button>
    </div>
  );
}

/** Read-only email above new-password fields: tells people (and password managers)
 *  which account the password belongs to. */
export function AccountEmailField({ label, email }: { label: string; email: string }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      <Input type="email" name="username" autoComplete="username" value={email} readOnly />
    </label>
  );
}

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
