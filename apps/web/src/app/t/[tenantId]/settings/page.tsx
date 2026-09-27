import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Card, PageTitle } from "@/components/ui";
import { requireMe } from "@/lib/server-api";

const ITEMS = ["plan", "brand", "connections", "members", "evals"] as const;

export default async function SettingsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  if (!me.memberships.some((m) => m.tenant_id === tenantId)) redirect("/");
  const t = await getTranslations("settingsHub");
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      <div className="grid gap-3 sm:grid-cols-2">
        {ITEMS.map((k) => (
          <Link key={k} href={`/t/${tenantId}/${k}`} className="block">
            <Card className="h-full transition hover:border-accent">
              <p className="font-semibold">{t(`${k}.title`)}</p>
              <p className="mt-1 text-sm text-muted">{t(`${k}.hint`)}</p>
            </Card>
          </Link>
        ))}
      </div>
    </>
  );
}
