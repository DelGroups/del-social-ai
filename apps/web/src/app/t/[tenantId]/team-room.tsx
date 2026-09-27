"use client";

// The Team Room: chat with the Team Lead (tasks and approvals appear in it) and the live team.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApprovalCard } from "@/components/approval-card";
import { ApiError, api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { ChatMsg, LiveInfo, TaskInfo } from "@/lib/types";

import { LiveStudio } from "./live-studio";

const AGENT_STYLE: Record<string, { letter: string; color: string }> = {
  team_lead: { letter: "R", color: "#6C5CE7" },
  media_analyst: { letter: "Ş", color: "#0E9F9F" },
  copywriter: { letter: "K", color: "#E0752D" },
  brand_guardian: { letter: "N", color: "#2F8F6B" },
  visual_editor: { letter: "V", color: "#C2549B" },
  publisher: { letter: "P", color: "#3B6FD8" },
};
const POLL_MS = 3000;

function Avatar({ agent, size = 30 }: { agent: string; size?: number }) {
  const s = AGENT_STYLE[agent] ?? { letter: "?", color: "#777" };
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full font-semibold text-white"
      style={{ background: s.color, width: size, height: size, fontSize: size * 0.4 }}
      aria-hidden="true"
    >
      {s.letter}
    </span>
  );
}

function TaskCard({ task }: { task: TaskInfo }) {
  const t = useTranslations("team");
  return (
    <div className="w-full max-w-md space-y-2 rounded-lg border border-border bg-surface p-3">
      <p className="text-sm font-semibold">{task.title}</p>
      <ol className="space-y-1">
        {task.steps.map((s) => (
          <li key={s.key} className="flex items-center gap-2 text-sm">
            <span
              className={`grid h-4 w-4 place-items-center rounded-full border-2 text-[10px] text-white ${
                s.status === "done"
                  ? "border-success bg-success"
                  : s.status === "running"
                    ? "animate-spin border-accent border-t-transparent"
                    : s.status === "waiting"
                      ? "border-accent bg-accent"
                      : s.status === "failed"
                        ? "border-danger bg-danger"
                        : "border-border"
              }`}
            >
              {s.status === "done" ? "✓" : s.status === "waiting" ? "!" : s.status === "failed" ? "×" : ""}
            </span>
            <span className={s.status === "pending" ? "text-muted" : ""}>{t(`steps.${s.key}`)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function TeamRoom({ tenantId, canAct }: { tenantId: string; canAct: boolean }) {
  const t = useTranslations("team");
  const tc = useTranslations("common");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [live, setLive] = useState<LiveInfo | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const feed = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const [m, l] = await Promise.all([
        api<ChatMsg[]>(`/tenants/${tenantId}/team/chat`),
        api<LiveInfo>(`/tenants/${tenantId}/team/live`),
      ]);
      setMessages(m);
      setLive(l);
    } catch {
      /* keep the last view; the next poll retries */
    }
  }, [tenantId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (messages.length !== lastCount.current) {
      lastCount.current = messages.length;
      feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    const value = text.trim();
    if (!value) return;
    setSending(true);
    setError(null);
    try {
      await api(`/tenants/${tenantId}/team/chat`, { method: "POST", body: { text: value } });
      setText("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setSending(false);
    }
  }

  const leadBusy = live?.agents.find((a) => a.agent === "team_lead")?.state === "working";
  const kpis: [string, string | number, string?][] = live
    ? [
        [t("kpi.waiting"), live.waiting.length, live.waiting.length ? "accent" : undefined],
        [t("kpi.running"), live.running.length],
        [t("kpi.scheduled"), live.scheduled.length, undefined],
        [t("kpi.published"), live.published.length],
      ]
    : [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {kpis.map(([label, value, tone]) => (
          <div key={label} className={`rounded-lg border bg-surface px-3 py-2 ${tone === "accent" ? "border-accent" : "border-border"}`}>
            <p className="text-xs text-muted">{label}</p>
            <p className={`text-lg font-semibold tabular-nums ${tone === "accent" ? "text-accent" : ""}`}>{value}</p>
          </div>
        ))}
      </div>

      <LiveStudio live={live} />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <section className="flex min-h-[560px] flex-col rounded-lg border border-border bg-surface" aria-label={t("chatTitle")}>
          <div className="flex items-center gap-3 border-b border-border px-4 py-3">
            <Avatar agent="team_lead" size={34} />
            <div>
              <p className="text-sm font-semibold">{t("agents.team_lead")}</p>
              <p className="text-xs text-muted">{leadBusy ? t("leadThinking") : t("leadIdle")}</p>
            </div>
          </div>

          <div ref={feed} className="flex max-h-[62vh] flex-1 flex-col gap-3 overflow-y-auto p-4" aria-live="polite">
            {messages.length === 0 && <p className="text-sm text-muted">{t("empty")}</p>}
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.message_id} className="self-end max-w-xl rounded-lg bg-accent px-3 py-2 text-sm text-accent-text whitespace-pre-wrap">
                  {m.text}
                </div>
              ) : (
                <div key={m.message_id} className="flex max-w-3xl gap-2">
                  <Avatar agent={m.agent ?? "team_lead"} />
                  <div className="min-w-0 flex-1 space-y-2">
                    <p className="text-xs text-muted">
                      {t(`agents.${m.agent ?? "team_lead"}`)} · {formatDateTime(m.created_at)}
                    </p>
                    <p className="whitespace-pre-wrap rounded-lg bg-bg px-3 py-2 text-sm">{m.text}</p>
                    {m.task && <TaskCard task={m.task} />}
                    {m.post && <ApprovalCard tenantId={tenantId} post={m.post} canAct={canAct} onChange={refresh} />}
                  </div>
                </div>
              ),
            )}
            {leadBusy && <p className="text-xs text-muted">{t("leadThinking")}</p>}
          </div>

          <form onSubmit={send} className="space-y-2 border-t border-border p-3">
            <div className="flex flex-wrap gap-2">
              {["suggest1", "suggest2", "suggest3"].map((k) => (
                <button key={k} type="button" onClick={() => setText(t(k))} className="rounded-full border border-border px-3 py-1 text-xs text-muted hover:border-accent hover:text-text">
                  {t(k)}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                rows={2}
                maxLength={2000}
                placeholder={t("placeholder")}
                className="min-w-0 flex-1 resize-none rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none"
              />
              <button type="submit" disabled={sending || !text.trim()} className="self-end rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text disabled:opacity-50">
                {t("send")}
              </button>
            </div>
            {error && <p className="text-sm text-danger">{error}</p>}
          </form>
        </section>

        <aside className="space-y-4" aria-label={t("activity")}>
          <div className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("upcoming")}</h2>
            {(live?.scheduled ?? []).length === 0 ? (
              <p className="text-sm text-muted">{t("noneScheduled")}</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {live!.scheduled.map((p) => (
                  <li key={p.post_id}>
                    <Link href={`/t/${tenantId}/posts/${p.post_id}`} className="flex items-center gap-2 hover:text-accent">
                      {p.photos[0] && <img src={p.photos[0].url} alt="" className="h-8 w-8 rounded object-cover" />}
                      <span className="tabular-nums">{p.scheduled_at ? formatDateTime(p.scheduled_at) : ""}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {(live?.published ?? []).length > 0 && (
            <div className="space-y-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("recentlyPublished")}</h2>
              <ul className="space-y-1 text-sm">
                {live!.published.map((p) => (
                  <li key={p.post_id} className="flex items-center gap-2">
                    {p.photos[0] && <img src={p.photos[0].url} alt="" className="h-8 w-8 rounded object-cover" />}
                    <span className="text-xs text-muted tabular-nums">{p.published_at ? formatDateTime(p.published_at) : ""}</span>
                    {Object.entries(p.results).map(([c, r]) =>
                      r.url ? (
                        <a key={c} href={r.url} target="_blank" rel="noreferrer" className="text-xs text-accent underline">
                          {c}
                        </a>
                      ) : null,
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">{t("activity")}</h2>
            <ul className="max-h-64 space-y-1 overflow-y-auto text-xs">
              {(live?.events ?? []).map((e) => (
                <li key={`${e.at}${e.title}`} className="ls-slide flex gap-2">
                  <span className="shrink-0 tabular-nums text-muted">{formatDateTime(e.at).slice(-5)}</span>
                  <span className={e.kind === "failed" ? "text-danger" : ""}>
                    <b className="font-medium">{t(`agents.${e.agent}`)}</b> · {e.title}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {live && (
            <div className="space-y-1 text-xs text-muted">
              {live.connections.map((c) => (
                <p key={c.channel + c.name}>
                  <span className={c.status === "active" ? "text-success" : "text-danger"}>●</span> {c.channel} · {c.name}
                </p>
              ))}
              {live.photos_unanalysed > 0 && <p>{t("unanalysed", { count: live.photos_unanalysed })}</p>}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
