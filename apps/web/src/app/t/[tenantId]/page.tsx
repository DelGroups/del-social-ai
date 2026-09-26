import { redirect } from "next/navigation";

import { requireMe } from "@/lib/server-api";
import { canApprove } from "@/lib/types";

import { TeamRoom } from "./team-room";

export default async function TeamRoomPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/"); // the layout redirects too, but pages render in parallel
  return <TeamRoom tenantId={tenantId} canAct={canApprove(membership.role)} />;
}
