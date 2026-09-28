"use client";

// Reports: the deep review laid out by area, and the history of pulses and daily reports.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { YtReport } from "@/lib/youtube";

import { CostButton, ReportBody, StudioGate, errorText, useDashboard, usePoll } from "./common";

const GRADE: Record<string, string> = { strong: "bg-success/15 text-success", ok: "bg-accent/15 text-accent", weak: "bg-danger/15 text-danger", unknown: "bg-bg text-muted" };

function Review({ r }: { r: YtReport }) {
  const t = useTranslations("yt");
  const o = r.output ?? {};
  return (
    <div className="space-y-4">
      <div>
        <p className="text-lg font-semibold" dir="auto">{o.headline}</p>
        <p className="text-sm text-muted" dir="auto">{o.summary}</p>
      </div>
      {Array.isArray(o.top_actions) && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("topActions")}</h4>
          <ol className="space-y-2">
            {o.top_actions.map((a: any, i: number) => (
              <li key={a.title} className="flex gap-3 rounded-lg bg-bg p-3 text-sm">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#FF0000] text-xs font-bold text-white">{i + 1}</span>
                <div className="space-y-1">
                  <p className="font-medium" dir="auto">{a.title}</p>
                  <p className="text-muted" dir="auto">{a.why}</p>
                  <p dir="auto">{a.how}</p>
                  <p className="text-[11px] text-muted">{t("effort")}: {t(`level.${a.effort}`)} · {t("impact")}: {t(`level.${a.impact}`)}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
      {Array.isArray(o.areas) && (
        <div className="grid gap-3 md:grid-cols-2">
          {o.areas.map((a: any) => (
            <div key={a.area} className="space-y-1.5 rounded-lg border border-border p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <b>{t(`area.${a.area}`)}</b>
                <span className={`rounded-full px-2 py-0.5 text-[11px] ${GRADE[a.grade] ?? GRADE.unknown}`}>{t(`grade.${a.grade}`)}</span>
              </div>
              <p dir="auto">{a.finding}</p>
              <p className="text-xs text-muted" dir="auto">{a.evidence}</p>
              <ul className="list-disc pl-5 text-xs">{(a.advice ?? []).map((x: string) => <li key={x} dir="auto">{x}</li>)}</ul>
            </div>
          ))}
        </div>
      )}
      {Array.isArray(o.experiments) && o.experiments.length > 0 && (
        <div className="text-sm">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t("experiments")}</h4>
          <ul className="list-disc pl-5">{o.experiments.map((x: string) => <li key={x} dir="auto">{x}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export function YtReports({ tenantId, canWork }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt");
  const { data } = useDashboard(tenantId);
  const [kind, setKind] = useState<"review" | "daily" | "pulse">("review");
  const [rows, setRows] = useState<YtReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/tenants/${tenantId}/youtube/reports`;
  const load = useCallback(async () => {
    try {
      setRows(await api<YtReport[]>(`${base}?kind=${kind}`));
    } catch {
      setRows([]);
    }
  }, [base, kind]);
  useEffect(() => {
    if (data?.connection && data.addon.active) load();
  }, [data?.connection, data?.addon.active, load]);
  usePoll(!!rows?.some((r) => r.status === "running"), load);

  async function run() {
    setError(null);
    try {
      await api(`${base}/${kind}`, { method: "POST" });
      await load();
    } catch (err) {
      setError(errorText(err, t("error")));
    }
  }

  return (
    <StudioGate tenantId={tenantId} data={data}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {(["review", "daily", "pulse"] as const).map((k) => (
            <button key={k} type="button" onClick={() => setKind(k)}
              className={`rounded-full border px-3 py-1 text-xs ${kind === k ? "border-accent bg-accent/10 text-accent" : "border-border text-muted"}`}>
              {t(`reportKind.${k}`)}
            </button>
          ))}
          {canWork && (
            <div className="ml-auto">
              <CostButton cost={kind === "review" ? data?.addon.costs.review : undefined} busy={!!rows?.some((r) => r.status === "running")} onClick={run}>
                {t(`reportRun.${kind}`)}
              </CostButton>
            </div>
          )}
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        {rows === null ? <div className="wf-skeleton h-32 rounded-xl" /> : rows.length === 0 ? (
          <p className="text-sm text-muted">{t("noReports")}</p>
        ) : (
          <div className="space-y-4">
            {rows.map((r, i) => (
              <details key={r.report_id} open={i === 0} className="rounded-xl border border-border bg-surface p-4">
                <summary className="cursor-pointer text-sm">
                  <span className="text-muted">{formatDateTime(r.created_at)}</span>
                  {r.status === "done" && r.output?.headline && <b className="ml-2" dir="auto">{r.output.headline}</b>}
                  {r.status !== "done" && <span className="ml-2 text-xs text-muted">{t(`status.${r.status}`)}</span>}
                </summary>
                <div className="mt-3">{r.kind === "review" && r.status === "done" ? <Review r={r} /> : <ReportBody report={r} />}</div>
              </details>
            ))}
          </div>
        )}
      </div>
    </StudioGate>
  );
}
