import { getTranslations } from "next-intl/server";

import { AuthFrame } from "@/components/shell";
import { Alert } from "@/components/ui";
import { apiGet } from "@/lib/server-api";

import { ResetForm } from "./reset-form";

export default async function ResetPasswordPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const t = await getTranslations("reset");
  const { data } = await apiGet<{ email: string }>(`/auth/password-resets/${encodeURIComponent(token)}`);
  return (
    <AuthFrame title={t("title")}>
      {data ? <ResetForm token={token} email={data.email} /> : <Alert tone="error">{t("invalid")}</Alert>}
    </AuthFrame>
  );
}
