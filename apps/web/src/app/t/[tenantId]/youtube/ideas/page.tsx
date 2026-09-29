import { redirect } from "next/navigation";

import { YtIdeas } from "@/components/youtube/ideas";
import { requireMe } from "@/lib/server-api";
import { canApprove, canManageBrand } from "@/lib/types";

export default async function Page({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  return <YtIdeas tenantId={tenantId} canWork={canApprove(membership.role)} canManage={canManageBrand(membership.role)} />;
}
