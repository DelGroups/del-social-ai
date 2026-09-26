"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PasswordInput } from "@/components/client";
import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { Me } from "@/lib/types";

export function LoginForm({ next }: { next: string }) {
  const t = useTranslations();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/login", {
        method: "POST",
        body: { email: form.get("email"), password: form.get("password") },
      });
      const target =
        next === "/" && me.memberships.length === 1 && !me.is_platform_admin
          ? `/t/${me.memberships[0].tenant_id}`
          : next;
      router.push(target);
      router.refresh();
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(status === 401 ? t("login.invalid") : status === 429 ? t("common.tooMany") : t("common.error"));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Field label={t("login.email")}>
        <Input name="email" type="email" autoComplete="email" required autoFocus />
      </Field>
      <Field label={t("login.password")}>
        <PasswordInput name="password" autoComplete="current-password" required />
      </Field>
      {error && <Alert tone="error">{error}</Alert>}
      <Button type="submit" disabled={busy} className="w-full">
        {t("login.submit")}
      </Button>
      <p className="text-xs text-muted">{t("login.forgot")}</p>
    </form>
  );
}
