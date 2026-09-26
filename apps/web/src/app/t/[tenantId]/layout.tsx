import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { Shell } from "@/components/shell";
import { requireMe } from "@/lib/server-api";

export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  const me = await requireMe(`/t/${tenantId}`);
  // Only hides the page; the API re-checks membership on every request
  if (!me.memberships.some((m) => m.tenant_id === tenantId)) redirect("/");
  const t = await getTranslations("tenant");
  return (
    <Shell
      me={me}
      tenantId={tenantId}
      nav={[
        { href: `/t/${tenantId}`, label: t("overview") },
        { href: `/t/${tenantId}/members`, label: t("members") },
        { href: `/t/${tenantId}/connections`, label: t("connections") },
      ]}
    >
      {children}
    </Shell>
  );
}
