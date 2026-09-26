import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { Alert, Card, PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { apiGet, requireMe } from "@/lib/server-api";
import { type PostInfo, type Usage, canViewUsage } from "@/lib/types";

const usd = (v: string) => `$${Number(v).toFixed(Number(v) < 1 ? 4 : 2)}`;

export default async function ReportsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const t = await getTranslations();
  const [{ data: posts }, usage] = await Promise.all([
    apiGet<PostInfo[]>(`/tenants/${tenantId}/posts`),
    canViewUsage(membership.role) ? apiGet<Usage>(`/tenants/${tenantId}/usage`) : Promise.resolve({ data: null }),
  ]);
  const published = (posts ?? []).filter((p) => p.status === "published" || p.status === "partly_published");
  return (
    <>
      <PageTitle>{t("reports.title")}</PageTitle>
      <div className="space-y-6">
        <Alert>{t("reports.soon")}</Alert>
        <Card title={t("reports.published", { count: published.length })}>
          {published.length === 0 ? (
            <p className="text-sm text-muted">{t("reports.nonePublished")}</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {published.map((p) => (
                <li key={p.post_id} className="flex flex-wrap items-center gap-3">
                  {p.photos[0] && <img src={p.photos[0].url} alt="" className="h-10 w-10 rounded object-cover" />}
                  <span className="tabular-nums text-muted">{p.published_at ? formatDateTime(p.published_at) : ""}</span>
                  <span className="line-clamp-1 min-w-0 flex-1">{p.caption}</span>
                  {Object.entries(p.results).map(([c, r]) =>
                    r.url ? (
                      <a key={c} href={r.url} target="_blank" rel="noreferrer" className="text-accent underline">{c}</a>
                    ) : null,
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
        {usage.data && (
          <Card title={t("usage.title", { month: usage.data.month })}>
            <p className="mb-3 text-2xl font-semibold">{usd(usage.data.cost_usd)}</p>
            <table className="w-full text-left text-sm">
              <tbody>
                {usage.data.by_agent.map((a) => (
                  <tr key={a.agent} className="border-t border-border">
                    <td className="py-2">{t(`team.agents.${a.agent}`)}</td>
                    <td className="py-2 text-muted">{t("usage.calls", { count: a.calls })}</td>
                    <td className="py-2 text-right tabular-nums">{usd(a.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </>
  );
}
