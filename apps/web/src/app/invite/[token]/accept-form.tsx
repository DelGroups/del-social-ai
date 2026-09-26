"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AccountEmailField, PasswordInput } from "@/components/client";
import { Alert, Button, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { Me } from "@/lib/types";

export function AcceptForm({ token, email, signedIn }: { token: string; email: string; signedIn: boolean }) {
  const t = useTranslations();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (!signedIn && form.get("password") !== form.get("confirm")) {
      setError(t("common.mismatch"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api<Me>(`/auth/invitations/${encodeURIComponent(token)}/accept`, {
        method: "POST",
        body: signedIn ? {} : { password: form.get("password") },
      });
      // Home opens the company directly when it's the only one, else shows the list
      router.push("/");
      router.refresh();
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 409) setNeedsSignIn(true);
      setError(
        status === 409
          ? t("invite.existingAccount")
          : status === 422 && err instanceof ApiError
            ? err.message
            : status === 410
              ? t("invite.accepted")
              : status === 429
                ? t("common.tooMany")
                : t("common.error"),
      );
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {!signedIn && (
        <>
          <AccountEmailField label={t("login.email")} email={email} />
          <Field label={t("invite.choosePassword")} hint={t("common.passwordHint")}>
            <PasswordInput name="password" autoComplete="new-password" minLength={10} maxLength={128} required />
          </Field>
          <Field label={t("invite.confirmPassword")}>
            <PasswordInput name="confirm" autoComplete="new-password" required />
          </Field>
        </>
      )}
      {error && <Alert tone="error">{error}</Alert>}
      {needsSignIn ? (
        <Link
          href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}
          className="block text-center text-sm underline"
        >
          {t("invite.signInToAccept")}
        </Link>
      ) : (
        <Button type="submit" disabled={busy} className="w-full">
          {t("invite.accept")}
        </Button>
      )}
    </form>
  );
}
