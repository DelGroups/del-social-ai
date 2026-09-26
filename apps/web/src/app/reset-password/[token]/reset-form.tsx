"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { AccountEmailField, PasswordInput } from "@/components/client";
import { Alert, Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";

export function ResetForm({ token, email }: { token: string; email: string }) {
  const t = useTranslations();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  if (done) {
    return (
      <div className="space-y-4">
        <Alert tone="success">{t("reset.done")}</Alert>
        <Link href="/login" className="block text-center text-sm underline">
          {t("reset.goToLogin")}
        </Link>
      </div>
    );
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (form.get("password") !== form.get("confirm")) {
      setError(t("common.mismatch"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(`/auth/password-resets/${encodeURIComponent(token)}`, {
        method: "POST",
        body: { new_password: form.get("password") },
      });
      setDone(true);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(
        status === 410
          ? t("reset.invalid")
          : status === 422 && err instanceof ApiError
            ? err.message
            : status === 429
              ? t("common.tooMany")
              : t("common.error"),
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <AccountEmailField label={t("login.email")} email={email} />
      <Field label={t("reset.newPassword")} hint={t("common.passwordHint")}>
        <PasswordInput name="password" autoComplete="new-password" minLength={10} maxLength={128} required />
      </Field>
      <Field label={t("reset.confirm")}>
        <PasswordInput name="confirm" autoComplete="new-password" required />
      </Field>
      {error && <Alert tone="error">{error}</Alert>}
      <Button type="submit" disabled={busy} className="w-full">
        {t("reset.submit")}
      </Button>
    </form>
  );
}
