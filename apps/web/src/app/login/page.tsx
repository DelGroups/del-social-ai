import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { AuthFrame } from "@/components/shell";
import { safeNext } from "@/lib/client-api";
import { getMe } from "@/lib/server-api";

import { LoginForm } from "./login-form";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const next = safeNext((await searchParams).next);
  if (await getMe()) redirect(next);
  const t = await getTranslations("login");
  return (
    <AuthFrame title={t("title")}>
      <LoginForm next={next} />
    </AuthFrame>
  );
}
