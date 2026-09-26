"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { CopyField } from "@/components/client";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";

type Result = { text: string; url: string } | { error: string } | null;

function useSubmit(handler: (form: FormData) => Promise<{ text: string; url: string }>) {
  const t = useTranslations("common");
  const [result, setResult] = useState<Result>(null);
  const [busy, setBusy] = useState(false);
  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    setBusy(true);
    setResult(null);
    try {
      setResult(await handler(new FormData(formEl)));
      formEl.reset();
    } catch (err) {
      setResult({ error: err instanceof ApiError && err.status !== 500 ? err.message : t("error") });
    } finally {
      setBusy(false);
    }
  }
  return { result, busy, onSubmit };
}

function ResultBox({ result }: { result: Result }) {
  if (!result) return null;
  if ("error" in result) return <Alert tone="error">{result.error}</Alert>;
  return (
    <div className="space-y-2">
      <Alert tone="success">{result.text}</Alert>
      <CopyField value={result.url} />
    </div>
  );
}

export function PlatformForms() {
  const t = useTranslations("platform");

  const tenant = useSubmit(async (form) => {
    const email = String(form.get("owner_email"));
    const res = await api<{ owner_invitation_url: string }>("/platform/tenants", {
      method: "POST",
      body: { name: form.get("name"), owner_email: email },
    });
    return { text: t("tenantCreated", { email }), url: res.owner_invitation_url };
  });

  const reset = useSubmit(async (form) => {
    try {
      const res = await api<{ url: string }>("/platform/password-resets", {
        method: "POST",
        body: { email: form.get("email") },
      });
      return { text: t("resetCreated"), url: res.url };
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) throw new ApiError(404, t("noAccount"));
      throw err;
    }
  });

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card title={t("createTenant")}>
        <form onSubmit={tenant.onSubmit} className="space-y-4">
          <Field label={t("tenantName")}>
            <Input name="name" required maxLength={200} />
          </Field>
          <Field label={t("ownerEmail")}>
            <Input name="owner_email" type="email" required />
          </Field>
          <Button type="submit" disabled={tenant.busy}>
            {t("create")}
          </Button>
          <ResultBox result={tenant.result} />
        </form>
      </Card>
      <Card title={t("resetTitle")}>
        <form onSubmit={reset.onSubmit} className="space-y-4">
          <Field label={t("resetEmail")}>
            <Input name="email" type="email" required />
          </Field>
          <Button type="submit" disabled={reset.busy}>
            {t("issue")}
          </Button>
          <ResultBox result={reset.result} />
        </form>
      </Card>
    </div>
  );
}
