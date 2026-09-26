import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type MediaAsset, type ProductInfo, canManageMedia } from "@/lib/types";

import { MediaLibrary } from "./media-library";

export default async function MediaPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const [{ data }, { data: products }, t] = await Promise.all([
    apiGet<MediaAsset[]>(`/tenants/${tenantId}/media`),
    apiGet<ProductInfo[]>(`/tenants/${tenantId}/products`),
    getTranslations("media"),
  ]);
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      <MediaLibrary
        tenantId={tenantId}
        assets={data ?? []}
        products={products ?? []}
        canManage={canManageMedia(membership.role)}
      />
    </>
  );
}
