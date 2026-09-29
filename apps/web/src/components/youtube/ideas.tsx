"use client";

// Ideas board: video ideas with their evidence; keep the good ones, mark what was made, drop the rest.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { formatDate } from "@/lib/prefs";
import type { YtIdea, YtReport } from "@/lib/youtube";

import { CostButton, StudioGate, errorText, useDashboard, usePoll } from "./common";

export function YtIdeas({ tenantId, canWork }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt");
  const { data, load: loadDash } = useDashboard(tenantId);
  const [ideas, setIdeas] = useState<YtIdea[] | null>(null);
  const [tab, setTab] = useState<"new" | "saved" | "used">("new");
  const [error, setError] = useState<string | null>(null);
  const base = `/tenants/${tenantId}/youtube`;
  const load = useCallback(async () => {
    try {
      setIdeas(await api<YtIdea[]>(`${base}/ideas`));
    } catch {
      setIdeas([]);
    }
  }, [base]);
  useEffect(() => {
    if (data?.connection && data.addon.active) load();
  }, [data?.connection, data?.addon.active, load]);
  const running = data?.latest?.ideas?.status === "running";
  const refresh = useCallback(() => {
    loadDash();
    load();
  }, [loadDash, load]);
  usePoll(running, refresh, 4000);

  async function run() {
    setError(null);
    try {
      await api(`${base}/ideas/run`, { method: "POST" });
      await loadDash();
    } catch (err) {
      setError(errorText(err, t("error")));
    }
  }
  async function mark(id: string, status: YtIdea["status"]) {
    await api(`${base}/ideas/${id}`, { method: "PATCH", body: { status } });
    load();
  }
  const last: YtReport | null | undefined = data?.latest?.ideas;
  const shown = (ideas ?? []).filter((i) => i.status === tab);

  return (
    <StudioGate tenantId={tenantId} data={data}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-1">
            {(["new", "saved", "used"] as const).map((k) => (
              <button key={k} type="button" onClick={() => setTab(k)}
                className={`rounded-full border px-3 py-1 text-xs ${tab === k ? "border-accent bg-accent/10 text-accent" : "border-border text-muted"}`}>
                {t(`ideaTab.${k}`)} · {(ideas ?? []).filter((i) => i.status === k).length}
              </button>
            ))}
          </div>
          {canWork && <CostButton cost={data?.addon.costs.ideas} busy={running} onClick={run}>{t("ideasRun")}</CostButton>}
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        {last?.status === "done" && last.output?.summary && tab === "new" && (
          <section className="space-y-2 rounded-xl border border-border bg-surface p-4 text-sm">
            <p className="text-xs text-muted">{formatDate(last.created_at)}</p>
            <p dir="auto">{last.output.summary}</p>
            {Array.isArray(last.output.trends) && (
              <ul className="list-disc space-y-0.5 pl-5 text-muted">{last.output.trends.map((x: string) => <li key={x} dir="auto">{x}</li>)}</ul>
            )}
            {last.sources.length > 0 && (
              <p className="text-xs text-muted">
                {last.sources.map((s, i) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="mr-2 underline">[{i + 1}] {s.title}</a>)}
              </p>
            )}
          </section>
        )}
        {last?.status === "failed" && <p className="text-sm text-danger">{last.error}</p>}
        {running && <div className="wf-skeleton h-24 rounded-xl" />}
        {shown.length === 0 && !running ? (
          <p className="text-sm text-muted">{t("ideasEmpty")}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {shown.map((i) => (
              <article key={i.idea_id} className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-semibold leading-snug" dir="auto">{i.title}</h3>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${i.format === "short" ? "bg-[#FF0000]/15 text-[#FF4D4D]" : "bg-bg text-muted"}`}>
                    {t(`format.${i.format}`)}
                  </span>
                </div>
                <p className="text-sm" dir="auto">{i.angle}</p>
                <p className="rounded-md bg-bg p-2 text-xs" dir="auto"><b>{t("hook")}:</b> {i.hook}</p>
                <p className="text-xs text-muted" dir="auto"><b>{t("why")}:</b> {i.why} <span className="opacity-70">{i.evidence}</span></p>
                <p className="text-xs text-muted" dir="auto"><b>{t("thumbIdea")}:</b> {i.thumbnail}</p>
                <div className="flex flex-wrap gap-1">
                  {i.keywords.map((k) => <span key={k} className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted">{k}</span>)}
                  <span className="rounded-full bg-bg px-2 py-0.5 text-[11px]">{t(`difficulty.${i.difficulty}`)}</span>
                </div>
                {canWork && (
                  <div className="mt-auto flex gap-3 pt-1 text-xs">
                    {i.status !== "saved" && <button type="button" onClick={() => mark(i.idea_id, "saved")} className="text-accent underline">{t("keep")}</button>}
                    {i.status !== "used" && <button type="button" onClick={() => mark(i.idea_id, "used")} className="text-success underline">{t("made")}</button>}
                    <button type="button" onClick={() => mark(i.idea_id, "dismissed")} className="text-muted underline">{t("drop")}</button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </div>
    </StudioGate>
  );
}
