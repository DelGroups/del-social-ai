"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { PasswordInput } from "@/components/client";
import { Alert, Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";

export function PasswordForm() {
  const t = useTranslations();
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    if (form.get("new") !== form.get("confirm")) {
      setMessage({ tone: "error", text: t("common.mismatch") });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await api("/auth/password", {
        method: "POST",
        body: { current_password: form.get("current"), new_password: form.get("new") },
      });
      formEl.reset();
      setMessage({ tone: "success", text: t("account.changed") });
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      const text =
        status === 403
          ? t("account.wrongCurrent")
          : status === 422 && err instanceof ApiError
            ? err.message
            : status === 429
              ? t("common.tooMany")
              : t("common.error");
      setMessage({ tone: "error", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Field label={t("account.current")}>
        <PasswordInput name="current" autoComplete="current-password" required />
      </Field>
      <Field label={t("account.new")} hint={t("common.passwordHint")}>
        <PasswordInput name="new" autoComplete="new-password" minLength={10} maxLength={128} required />
      </Field>
      <Field label={t("reset.confirm")}>
        <PasswordInput name="confirm" autoComplete="new-password" required />
      </Field>
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
      <Button type="submit" disabled={busy}>
        {t("common.save")}
      </Button>
    </form>
  );
}
