import { getTranslations } from "next-intl/server";

import { AuthFrame } from "@/components/shell";

import { ResetForm } from "./reset-form";

export default async function ResetPasswordPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const t = await getTranslations("reset");
  return (
    <AuthFrame title={t("title")}>
      <ResetForm token={token} />
    </AuthFrame>
  );
}
