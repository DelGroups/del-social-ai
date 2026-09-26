import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type BrandProfileOut, type MediaAsset, canManageMedia } from "@/lib/types";

import { MediaLibrary } from "./media-library";

const EDITING_OFF = { background: false, remove_objects: false, enhance: false, recolor: false, swap_product: false };

export default async function MediaPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const [{ data }, { data: profile }, t] = await Promise.all([
    apiGet<MediaAsset[]>(`/tenants/${tenantId}/media`),
    apiGet<BrandProfileOut>(`/tenants/${tenantId}/brand-profile`),
    getTranslations("media"),
  ]);
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      <MediaLibrary
        tenantId={tenantId}
        assets={data ?? []}
        canManage={canManageMedia(membership.role)}
        editing={profile?.data.image_editing ?? EDITING_OFF}
      />
    </>
  );
}
