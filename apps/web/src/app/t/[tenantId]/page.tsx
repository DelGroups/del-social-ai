import { redirect } from "next/navigation";

import { apiGet, requireMe } from "@/lib/server-api";
import { type PlanStatus, canApprove } from "@/lib/types";

import { TeamRoom } from "./team-room";

export default async function TeamRoomPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/"); // the layout redirects too, but pages render in parallel
  const { data: plan } = await apiGet<PlanStatus>(`/tenants/${tenantId}/plan`);
  if (plan && !plan.plan && plan.addons?.some((a) => a.addon_id === "youtube" && a.active)) redirect(`/t/${tenantId}/youtube`);
  return <TeamRoom tenantId={tenantId} canAct={canApprove(membership.role)} />;
}
