import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PageTitle } from "@/components/ui";
import { requireMe } from "@/lib/server-api";
import { canApprove } from "@/lib/types";

import { ApprovalsInbox } from "./inbox";

export default async function ApprovalsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const t = await getTranslations("team");
  return (
    <>
      <PageTitle>{t("approvalsTitle")}</PageTitle>
      <ApprovalsInbox tenantId={tenantId} canAct={canApprove(membership.role)} />
    </>
  );
}
