import { getTranslations } from "next-intl/server";
import { notFound, redirect } from "next/navigation";

import { Card, PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { apiGet, requireMe } from "@/lib/server-api";
import { type EvalRunDetail, canApprove } from "@/lib/types";

import { RateBadge } from "../rate-badge";
import { EvalItems } from "./eval-items";

export default async function EvalRunPage({ params }: { params: Promise<{ tenantId: string; runId: string }> }) {
  const { tenantId, runId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const [{ data: run }, t] = await Promise.all([
    apiGet<EvalRunDetail>(`/tenants/${tenantId}/evals/${runId}`),
    getTranslations("evals"),
  ]);
  if (!run) notFound();
  return (
    <>
      <PageTitle>{t(`suite.${run.suite}`)}</PageTitle>
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <RateBadge rate={run.success_rate} target={run.target} />
          <span>{t("successes", { successes: run.successes, rated: run.rated })}</span>
          <span className="text-muted">
            {t("progress", { completed: run.completed, total: run.briefs_total, rated: run.rated })}
          </span>
          <span className="text-muted">${Number(run.cost_usd).toFixed(2)}</span>
          <span className="text-muted">{formatDateTime(run.created_at)}</span>
        </div>
        <p className="mt-3 text-xs text-muted">
          {t("versions", { brand: run.brand_version, prompts: Object.values(run.prompt_refs).join(", ") })}
        </p>
        {run.suite === "copywriter" && <p className="mt-3 text-sm text-muted">{t("howToRate")}</p>}
      </Card>
      <EvalItems tenantId={tenantId} run={run} canRate={canApprove(membership.role)} />
    </>
  );
}
