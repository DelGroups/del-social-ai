import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { Shell } from "@/components/shell";
import { Alert, PageTitle } from "@/components/ui";
import { requireMe } from "@/lib/server-api";

import { PlatformForms } from "./platform-forms";

export default async function PlatformPage() {
  const me = await requireMe("/platform");
  if (!me.is_platform_admin) notFound(); // the API enforces this too
  const t = await getTranslations("platform");
  return (
    <Shell me={me}>
      <PageTitle>{t("title")}</PageTitle>
      <div className="mb-6">
        <Alert>{t("note")}</Alert>
      </div>
      <PlatformForms />
    </Shell>
  );
}
