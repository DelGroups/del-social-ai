"use client";

// Comments inbox: new comments and the team's reply drafts. The owner picks who answers: a person (manual),
// the community manager with a person's approval, or the community manager by itself (automatic mode;
// replies that fail the code checks wait here with the reason).
import { useTranslations } from "next-intl";
import { type CSSProperties, useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { YtComment, YtReplyMode } from "@/lib/youtube";

import { CostButton, StudioGate, errorText, useDashboard } from "./common";
import { YT_AGENTS } from "./team";

const MODES: { id: YtReplyMode; icon: string }[] = [
  { id: "manual", icon: "M18 11V6a2 2 0 0 0-4 0v5M14 10V4a2 2 0 0 0-4 0v6M10 10.5V6a2 2 0 0 0-4 0v8a8 8 0 0 0 16 0v-3a2 2 0 0 0-4 0" },
  { id: "approval", icon: "M9 12l2 2 4-4M12 3l7 4v5c0 4.5-3 8-7 9-4-1-7-4.5-7-9V7z" },
  { id: "auto", icon: "M13 2 3 14h9l-1 8 10-12h-9z" },
];

function ModePicker({ tenantId, mode, cost, canManage, onChange }: {
  tenantId: string; mode: YtReplyMode; cost?: number; canManage: boolean; onChange: () => void;
}) {
  const t = useTranslations("yt.replyMode");
  const [busy, setBusy] = useState<YtReplyMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const color = YT_AGENTS.yt_replies?.color ?? "var(--accent)";
  async function pick(m: YtReplyMode) {
    if (m === mode || !canManage) return;
    setBusy(m);
    setError(null);
    try {
      await api(`/tenants/${tenantId}/youtube/comments/mode`, { method: "PUT", body: { mode: m } });
      onChange();
    } catch (err) {
      setError(errorText(err, t("title")));
    } finally {
      setBusy(null);
    }
  }
  return (
    <section className="space-y-3 rounded-xl border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold">{t("title")}</h2>
      <div role="radiogroup" aria-label={t("title")} className="grid gap-2 sm:grid-cols-3">
        {MODES.map(({ id, icon }) => {
          const on = id === mode;
          return (
            <button key={id} type="button" role="radio" aria-checked={on} disabled={!canManage || busy !== null} onClick={() => pick(id)}
              className={`relative flex items-start gap-3 overflow-hidden rounded-lg border p-3 text-start transition ${
                on ? "border-accent bg-accent/10" : "border-border hover:border-accent"} disabled:cursor-default ${busy === id ? "opacity-60" : ""}`}>
              {on && id !== "manual" && <span className="wf-sweep pointer-events-none absolute inset-0" style={{ ["--c" as string]: color } as CSSProperties} />}
              <span className={`relative grid h-8 w-8 shrink-0 place-items-center rounded-full ${on ? "bg-accent text-accent-text" : "bg-bg text-muted"}`}>
                <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d={icon} />
                </svg>
              </span>
              <span className="relative min-w-0">
                <span className="flex items-center gap-1.5 text-sm font-semibold">
                  {t(id)}
                  {on && id === "auto" && <span className="wf-dot inline-block h-1.5 w-1.5 rounded-full bg-accent" />}
                </span>
                <span className="mt-0.5 block text-xs text-muted">{t(`${id}Hint`)}</span>
              </span>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted">{mode === "manual" ? "" : t("cost", { n: cost ?? 1 })}{!canManage ? ` ${t("managersOnly")}` : ""}</p>
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}

export function YtComments({ tenantId, canWork, canManage = false }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt");
  const { data, load: reloadDashboard } = useDashboard(tenantId);
  const [state, setState] = useState<"open" | "sent" | "dismissed">("open");
  const [rows, setRows] = useState<YtComment[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/tenants/${tenantId}/youtube/comments`;
  const load = useCallback(async () => {
    try {
      setRows(await api<YtComment[]>(`${base}?state=${state}`));
    } catch {
      setRows([]);
    }
  }, [base, state]);
  useEffect(() => {
    if (data?.connection && data.addon.active) load();
  }, [data?.connection, data?.addon.active, load]);

  async function run(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(errorText(err, t("error")));
    } finally {
      setBusy(null);
    }
  }
  const toggle = (id: string) => setPicked((p) => {
    const n = new Set(p);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    return n;
  });
  const undrafted = (rows ?? []).filter((r) => r.status === "new");

  return (
    <StudioGate tenantId={tenantId} data={data}>
      <div className="space-y-4">
        {data?.settings && (
          <ModePicker tenantId={tenantId} mode={data.settings.reply_mode ?? "manual"} cost={data.addon.costs.comments}
            canManage={canManage} onChange={reloadDashboard} />
        )}
        <div className="flex flex-wrap items-center gap-2">
          {(["open", "sent", "dismissed"] as const).map((k) => (
            <button key={k} type="button" onClick={() => setState(k)}
              className={`rounded-full border px-3 py-1 text-xs ${state === k ? "border-accent bg-accent/10 text-accent" : "border-border text-muted"}`}>
              {t(`commentTab.${k}`)}
            </button>
          ))}
          {canWork && state === "open" && (
            <div className="ml-auto flex flex-wrap gap-2">
              <CostButton variant="ghost" busy={busy === "refresh"} onClick={() => run("refresh", () => api(`${base}/refresh`, { method: "POST" }))}>
                {t("checkComments")}
              </CostButton>
              <CostButton cost={data?.addon.costs.comments} busy={busy === "draft"} disabled={undrafted.length === 0 && picked.size === 0}
                onClick={() => run("draft", () => api(`${base}/draft`, { method: "POST", body: {
                  reply_ids: (picked.size ? [...picked] : undrafted.map((r) => r.reply_id)).slice(0, 20),
                } }))}>
                {t("draftReplies", { n: Math.min(20, picked.size || undrafted.length) })}
              </CostButton>
            </div>
          )}
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        {rows === null ? <div className="wf-skeleton h-32 rounded-xl" /> : rows.length === 0 ? (
          <p className="text-sm text-muted">{t("noComments")}</p>
        ) : (
          <ul className="space-y-3">
            {rows.map((c) => (
              <li key={c.reply_id} className="space-y-2 rounded-xl border border-border bg-surface p-4">
                <div className="flex items-start gap-3">
                  {state === "open" && canWork && (
                    <input type="checkbox" checked={picked.has(c.reply_id)} onChange={() => toggle(c.reply_id)} className="mt-1" aria-label={c.author} />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-muted">
                      <b className="text-text">{c.author}</b> · {c.published_at ? formatDateTime(c.published_at) : ""} · <span dir="auto">{c.video_title}</span>
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-sm" dir="auto">{c.text}</p>
                  </div>
                </div>
                {(c.status === "drafted" || c.status === "sent") && (
                  <div className="space-y-2 border-s-2 border-[#FF0000] ps-3">
                    {c.status === "sent" ? (
                      <>
                        <p className="text-sm" dir="auto">{c.draft}</p>
                        {c.sent_by && (
                          <p className="flex items-center gap-1.5 text-xs text-muted">
                            {c.sent_by === "agent" && <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: YT_AGENTS.yt_replies?.color }} />}
                            {t(`sentBy.${c.sent_by}`)}{c.sent_at ? ` · ${formatDateTime(c.sent_at)}` : ""}
                          </p>
                        )}
                      </>
                    ) : (
                      <>
                        {c.hold && (
                          <p className="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2 py-0.5 text-xs text-accent">
                            <svg viewBox="0 0 24 24" width={12} height={12} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
                              <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
                            </svg>
                            {t(`hold.${c.hold}`)}
                          </p>
                        )}
                        <textarea value={edits[c.reply_id] ?? c.draft} onChange={(e) => setEdits({ ...edits, [c.reply_id]: e.target.value })}
                          rows={2} dir="auto" className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none" />
                        {canWork && (
                          <div className="flex gap-2">
                            <CostButton busy={busy === c.reply_id} onClick={() => run(c.reply_id, () => api(`${base}/${c.reply_id}/send`, {
                              method: "POST", body: { text: edits[c.reply_id] ?? c.draft } }))}>{t("send")}</CostButton>
                            <CostButton variant="ghost" onClick={() => run(`d${c.reply_id}`, () => api(`${base}/${c.reply_id}/dismiss`, { method: "POST" }))}>{t("skip")}</CostButton>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
                {c.status === "new" && state === "open" && canWork && (
                  <button type="button" onClick={() => run(`d${c.reply_id}`, () => api(`${base}/${c.reply_id}/dismiss`, { method: "POST" }))} className="text-xs text-muted underline">
                    {t("skip")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </StudioGate>
  );
}
