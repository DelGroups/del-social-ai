import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { Alert, Card, PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { apiGet, requireMe } from "@/lib/server-api";
import type { PostInfo } from "@/lib/types";


export default async function ReportsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const t = await getTranslations();
  const { data: posts } = await apiGet<PostInfo[]>(`/tenants/${tenantId}/posts`);
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
      </div>
    </>
  );
}
