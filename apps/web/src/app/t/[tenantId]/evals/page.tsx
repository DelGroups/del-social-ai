import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Alert, Card, PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { apiGet, requireMe } from "@/lib/server-api";
import type { EvalRunSummary } from "@/lib/types";

import { RateBadge } from "./rate-badge";

export default async function EvalsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  if (!me.memberships.some((m) => m.tenant_id === tenantId)) redirect("/");
  const [{ data: runs }, t] = await Promise.all([
    apiGet<EvalRunSummary[]>(`/tenants/${tenantId}/evals`),
    getTranslations("evals"),
  ]);
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      <p className="mb-6 text-sm text-muted">{t("intro")}</p>
      {!runs || runs.length === 0 ? (
        <Alert>{t("empty")}</Alert>
      ) : (
        <div className="space-y-3">
          {runs.map((r) => (
            <Link key={r.run_id} href={`/t/${tenantId}/evals/${r.run_id}`} className="block">
              <Card className="transition hover:border-accent">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <span className="font-medium">{t(`suite.${r.suite}`)}</span>
                  <span className="text-muted">{formatDateTime(r.created_at)}</span>
                  <span className="text-muted">
                    {t("progress", { completed: r.completed, total: r.briefs_total, rated: r.rated })}
                  </span>
                  <span className="text-muted">${Number(r.cost_usd).toFixed(2)}</span>
                  <span className="ml-auto">
                    <RateBadge rate={r.success_rate} target={r.target} />
                  </span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
