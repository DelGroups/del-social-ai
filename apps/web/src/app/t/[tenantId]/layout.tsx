import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PlanBar } from "@/components/plan-bar";
import { Shell } from "@/components/shell";
import { apiGet, requireMe } from "@/lib/server-api";
import type { PlanStatus } from "@/lib/types";

export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const me = await requireMe(`/t/${tenantId}`);
  // Only hides the page; the API re-checks membership on every request
  if (!me.memberships.some((m) => m.tenant_id === tenantId)) redirect("/");
  const t = await getTranslations("tenant");
  const { data: plan } = await apiGet<PlanStatus>(`/tenants/${tenantId}/plan`);
  return (
    <Shell
      me={me}
      tenantId={tenantId}
      nav={[
        { href: `/t/${tenantId}`, label: t("home") },
        { href: `/t/${tenantId}/approvals`, label: t("approvals") },
        { href: `/t/${tenantId}/posts`, label: t("posts") },
        { href: `/t/${tenantId}/media`, label: t("media") },
        { href: `/t/${tenantId}/reports`, label: t("reports") },
        { href: `/t/${tenantId}/settings`, label: t("settings") },
      ]}
    >
      <PlanBar tenantId={tenantId} plan={plan} />
      {children}
    </Shell>
  );
}
