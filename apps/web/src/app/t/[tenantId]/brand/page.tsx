import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { Alert, PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type BrandProfileOut, canManageBrand } from "@/lib/types";

import { BrandForm } from "./brand-form";

export default async function BrandPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const [{ data }, t, tc] = await Promise.all([
    apiGet<BrandProfileOut>(`/tenants/${tenantId}/brand-profile`),
    getTranslations("brand"),
    getTranslations("common"),
  ]);
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      {data ? (
        // key: remount with fresh server data after each save
        <BrandForm
          key={data.version}
          tenantId={tenantId}
          canEdit={canManageBrand(membership.role)}
          initial={data}
        />
      ) : (
        <Alert tone="error">{tc("error")}</Alert>
      )}
    </>
  );
}
