import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { DailyActions } from "@/components/daily-actions";
import { CompetitorsPanel } from "@/components/strategy-panels";
import { Card, PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { apiGet, requireMe } from "@/lib/server-api";
import type { DailyRow, PostInfo } from "@/lib/types";

function ReportList({ tenantId, rows, empty }: { tenantId: string; rows: DailyRow[]; empty: string }) {
  if (rows.length === 0) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="divide-y divide-border">
      {rows.map((r) => (
        <li key={r.report_id}>
          <Link href={`/t/${tenantId}/reports/${r.report_id}`} className="flex items-center gap-3 py-2.5 text-sm hover:text-accent">
            <span className="w-24 shrink-0 tabular-nums text-muted">{r.day}</span>
            <span className={`min-w-0 flex-1 truncate ${r.status === "failed" ? "text-danger" : ""}`} dir="auto">
              {r.status === "running" ? "…" : r.status === "failed" ? r.error : r.headline}
            </span>
            <span aria-hidden="true">→</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default async function ReportsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const t = await getTranslations();
  const [{ data: posts }, { data: market }, { data: briefings }, { data: meetings }] = await Promise.all([
    apiGet<PostInfo[]>(`/tenants/${tenantId}/posts`),
    apiGet<DailyRow[]>(`/tenants/${tenantId}/daily?kind=market&limit=30`),
    apiGet<DailyRow[]>(`/tenants/${tenantId}/daily?kind=briefing&limit=30`),
    apiGet<DailyRow[]>(`/tenants/${tenantId}/daily?kind=meeting&limit=20`),
  ]);
  const published = (posts ?? []).filter((p) => p.status === "published" || p.status === "partly_published");
  const canRun = membership.role === "owner" || membership.role === "admin";
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <PageTitle>{t("reports.title")}</PageTitle>
        {canRun && <DailyActions tenantId={tenantId} />}
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={t("meeting.list")}>
          <p className="mb-3 text-xs text-muted">{t("meeting.listHint")}</p>
          <ReportList tenantId={tenantId} rows={meetings ?? []} empty={t("daily.noneYet")} />
        </Card>
        <Card title={t("competitors.title")} className="lg:col-span-2 lg:order-first">
          <CompetitorsPanel tenantId={tenantId} canManage={canRun} />
        </Card>
        <Card title={t("daily.marketList")}>
          <p className="mb-3 text-xs text-muted">{t("daily.marketListHint")}</p>
          <ReportList tenantId={tenantId} rows={market ?? []} empty={t("daily.noneYet")} />
        </Card>
        <Card title={t("daily.briefingList")}>
          <p className="mb-3 text-xs text-muted">{t("daily.briefingListHint")}</p>
          <ReportList tenantId={tenantId} rows={briefings ?? []} empty={t("daily.noneYet")} />
        </Card>
        <Card title={t("reports.published", { count: published.length })} className="lg:col-span-2">
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
        <p className="text-xs text-muted lg:col-span-2">{t("reports.soon")}</p>
      </div>
    </>
  );
}
