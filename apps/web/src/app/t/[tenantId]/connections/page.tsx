import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type BrandProfileOut, type ChannelInfo, type PageOption, canManageConnections } from "@/lib/types";

import { ConnectionsManager } from "./connections-manager";
import { PageSetup } from "./page-setup";

export default async function ConnectionsPage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string }>;
  searchParams: Promise<{ meta?: string; pick?: string }>;
}) {
  const { tenantId } = await params;
  const { meta, pick } = await searchParams;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const role = membership.role;
  const manage = canManageConnections(role);
  // After "Connect with Meta" the API sends people back here with ?meta=pick&pick=<id>
  const choosing = manage && meta === "pick" && pick;
  const [channels, pages, profile] = await Promise.all([
    apiGet<ChannelInfo[]>(`/tenants/${tenantId}/connections`),
    choosing
      ? apiGet<PageOption[]>(`/tenants/${tenantId}/connections/meta/pick/${encodeURIComponent(pick)}`)
      : Promise.resolve({ data: null }),
    apiGet<BrandProfileOut>(`/tenants/${tenantId}/brand-profile`),
  ]);
  const t = await getTranslations("connections");
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      <ConnectionsManager
        tenantId={tenantId}
        manage={manage}
        channels={channels.data ?? []}
        notice={meta && meta !== "pick" ? meta : null}
        pick={choosing ? { id: pick, pages: pages.data } : null}
      />
      <PageSetup tenantId={tenantId} channels={channels.data ?? []} profile={profile.data?.data ?? null} manage={manage} />
    </>
  );
}
