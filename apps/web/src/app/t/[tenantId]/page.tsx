import { getTranslations } from "next-intl/server";

import { Alert, Card, PageTitle } from "@/components/ui";
import { requireMe } from "@/lib/server-api";

export default async function TenantOverview({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId)!;
  const t = await getTranslations();
  return (
    <>
      <PageTitle>{t("tenant.welcome", { tenant: membership.tenant_name })}</PageTitle>
      <Card>
        <p className="mb-4 text-sm text-muted">
          {t("tenant.yourRole", { role: t(`roles.${membership.role}`) })}
        </p>
        <Alert>{t("tenant.comingSoon")}</Alert>
      </Card>
    </>
  );
}
