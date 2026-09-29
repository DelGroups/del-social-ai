"use client";

// Comments inbox: new comments, reply drafts written by the team, nothing sent until a person presses Send.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { YtComment } from "@/lib/youtube";

import { CostButton, StudioGate, errorText, useDashboard } from "./common";

export function YtComments({ tenantId, canWork }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt");
  const { data } = useDashboard(tenantId);
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
              <CostButton cost={data?.addon.costs.comments} busy={busy === "draft"} disabled={undrafted.length === 0}
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
                  {state === "open" && c.status === "new" && canWork && (
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
                  <div className="space-y-2 border-l-2 border-[#FF0000] pl-3">
                    {c.status === "sent" ? (
                      <p className="text-sm" dir="auto">{c.draft}</p>
                    ) : (
                      <>
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
