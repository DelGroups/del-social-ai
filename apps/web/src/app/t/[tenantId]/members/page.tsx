import { getTranslations } from "next-intl/server";

import { PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type Invitation, type Member, canManageMembers } from "@/lib/types";

import { MembersManager } from "./members-manager";

export default async function MembersPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const role = me.memberships.find((m) => m.tenant_id === tenantId)!.role;
  const manage = canManageMembers(role);
  const [members, invitations] = await Promise.all([
    apiGet<Member[]>(`/tenants/${tenantId}/members`),
    manage ? apiGet<Invitation[]>(`/tenants/${tenantId}/invitations`) : Promise.resolve({ data: [] }),
  ]);
  const t = await getTranslations("members");
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      <MembersManager
        tenantId={tenantId}
        myAccountId={me.account_id}
        myRole={role}
        members={members.data ?? []}
        invitations={invitations.data ?? []}
      />
    </>
  );
}
