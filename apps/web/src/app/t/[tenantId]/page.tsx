import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { Alert, Card, PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type Usage, canViewUsage } from "@/lib/types";

const usd = (v: string) => `$${Number(v).toFixed(Number(v) < 1 ? 4 : 2)}`;

export default async function TenantOverview({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/"); // the layout redirects too, but pages render in parallel
  const t = await getTranslations();
  const usage = canViewUsage(membership.role) ? (await apiGet<Usage>(`/tenants/${tenantId}/usage`)).data : null;
  return (
    <>
      <PageTitle>{t("tenant.welcome", { tenant: membership.tenant_name })}</PageTitle>
      <div className="space-y-6">
        <Card>
          <p className="mb-4 text-sm text-muted">
            {t("tenant.yourRole", { role: t(`roles.${membership.role}`) })}
          </p>
          <Alert>{t("tenant.comingSoon")}</Alert>
        </Card>
        {usage && (
          <Card title={t("usage.title", { month: usage.month })}>
            <p className="mb-4 text-sm">
              <span className="text-2xl font-semibold">{usd(usage.cost_usd)}</span>{" "}
              <span className="text-muted">{t("usage.calls", { count: usage.calls })}</span>
            </p>
            {usage.by_agent.length === 0 ? (
              <p className="text-sm text-muted">{t("usage.empty")}</p>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="text-muted">
                  <tr>
                    <th className="py-2 pr-4 font-medium">{t("usage.agent")}</th>
                    <th className="py-2 pr-4 font-medium">{t("usage.callsCol")}</th>
                    <th className="py-2 pr-4 font-medium">{t("usage.tokens")}</th>
                    <th className="py-2 font-medium">{t("usage.cost")}</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.by_agent.map((a) => (
                    <tr key={a.agent} className="border-t border-border">
                      <td className="py-2 pr-4">{a.agent.replaceAll("_", " ")}</td>
                      <td className="py-2 pr-4">
                        {a.calls}
                        {a.errors > 0 && <span className="text-danger"> ({t("usage.errors", { count: a.errors })})</span>}
                      </td>
                      <td className="py-2 pr-4 text-muted">
                        {a.input_tokens.toLocaleString("en-US")} / {a.output_tokens.toLocaleString("en-US")}
                      </td>
                      <td className="py-2">{usd(a.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}
      </div>
    </>
  );
}
