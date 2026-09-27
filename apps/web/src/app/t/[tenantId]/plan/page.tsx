import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { Alert, PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type PlanStatus, canBuyPlan } from "@/lib/types";

import { PlanView } from "./plan-view";

export default async function PlanPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const t = await getTranslations("plan");
  const { data } = await apiGet<PlanStatus>(`/tenants/${tenantId}/plan`);
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      {data ? <PlanView tenantId={tenantId} initial={data} canBuy={canBuyPlan(membership.role)} /> : <Alert tone="error">{t("loadError")}</Alert>}
    </>
  );
}
