import { getLocale, getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { PlanBar } from "@/components/plan-bar";
import { SideNav } from "@/components/side-nav";
import { apiGet, requireMe } from "@/lib/server-api";
import { DEFAULT_THEME, THEME_COOKIE, isTheme, previewAllowed } from "@/lib/prefs";
import type { LiveInfo, PlanStatus } from "@/lib/types";

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
  const [{ data: plan }, { data: live }] = await Promise.all([
    apiGet<PlanStatus>(`/tenants/${tenantId}/plan`),
    apiGet<LiveInfo>(`/tenants/${tenantId}/team/live`),
  ]);
  const base = `/t/${tenantId}`;
  const youtube = plan?.addons?.find((a) => a.addon_id === "youtube" && a.active);
  const social = plan?.plan != null || !youtube; // a YouTube-only company sees only its studio
  const themeCookie = (await cookies()).get(THEME_COOKIE)?.value;
  const prefs = { locale: await getLocale(), theme: isTheme(themeCookie) ? themeCookie : DEFAULT_THEME,
    preview: previewAllowed(me.is_platform_admin, tenantId) };
  return (
    <SideNav
      me={me}
      tenantId={tenantId}
      plan={plan}
      prefs={prefs}
      items={[
        ...(social
          ? ([
              { href: base, label: t("home"), icon: "home", exact: true },
              { href: `${base}/team`, label: t("team"), icon: "team" },
              { href: `${base}/approvals`, label: t("approvals"), icon: "check", badge: live?.waiting.length },
              { href: `${base}/posts`, label: t("posts"), icon: "posts" },
              { href: `${base}/media`, label: t("media"), icon: "photos" },
              { href: `${base}/reports`, label: t("reports"), icon: "reports" },
            ] as const)
          : []),
        ...(youtube ? [{ href: `${base}/youtube`, label: t("youtube"), icon: "youtube" as const }] : []),
        { href: `${base}/settings`, label: t("settings"), icon: "settings" },
      ]}
    >
      <PlanBar tenantId={tenantId} plan={plan} />
      {children}
    </SideNav>
  );
}
