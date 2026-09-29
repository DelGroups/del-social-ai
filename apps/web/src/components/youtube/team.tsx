"use client";

// YouTube team: talk to the Channel Manager; it hands work to the team, and each member reports
// back here with a link to what it made. The roster shows who is working right now.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";

import { StudioGate, errorText, useDashboard, usePoll } from "./common";

type Msg = { message_id: string; role: "user" | "agent"; agent: string | null; text: string; created_at: string;
  payload: { link?: "reports" | "ideas" | "comments" | "video"; video_id?: string; tab?: string } | null };
type Member = { agent: string; working: boolean; last_at: string | null };
type Room = { messages: Msg[]; roster: Member[]; lead_busy: boolean };

export const YT_AGENTS: Record<string, { color: string; icon: string }> = {
  yt_lead: { color: "#FF0033", icon: "M12 3l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 15.3l-4.8 2.6.9-5.4L4.2 8.7l5.4-.8z" },
  yt_reporter: { color: "#3B82F6", icon: "M4 20V10m6 10V4m6 16v-7m4 7H2" },
  yt_reviewer: { color: "#8B5CF6", icon: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm10 17-4.3-4.3" },
  yt_ideas: { color: "#F59E0B", icon: "M9 18h6m-5 3h4M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3z" },
  yt_metadata: { color: "#10B981", icon: "M4 6h16M4 12h16M4 18h10" },
  yt_thumbnail: { color: "#EC4899", icon: "M4 5h16v14H4zm4 4.5a1.5 1.5 0 1 0 0-.01M20 15l-5-5L6 19" },
  yt_replies: { color: "#06B6D4", icon: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z" },
  yt_editor: { color: "#F97316", icon: "M4 6h16v12H4zM8 6v12m8-12v12M4 10h4m8 0h4M4 14h4m8 0h4" },
};

function Face({ agent, size = 34, working = false }: { agent: string; size?: number; working?: boolean }) {
  const a = YT_AGENTS[agent] ?? YT_AGENTS.yt_lead;
  return (
    <span className="relative grid shrink-0 place-items-center rounded-full text-white" style={{ width: size, height: size, background: a.color, ["--ch-glow" as string]: a.color } as CSSProperties}>
      {working && <span className="ch-ping absolute inset-0 rounded-full" aria-hidden="true" />}
      <svg viewBox="0 0 24 24" width={size * 0.5} height={size * 0.5} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={a.icon} />
      </svg>
    </span>
  );
}

export function YtTeam({ tenantId, canWork }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt.team");
  const { data } = useDashboard(tenantId);
  const [room, setRoom] = useState<Room | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const feed = useRef<HTMLDivElement>(null);
  const count = useRef(0);
  const base = `/tenants/${tenantId}/youtube/team`;

  const load = useCallback(async () => {
    try {
      setRoom(await api<Room>(base));
    } catch {
      /* keep */
    }
  }, [base]);
  useEffect(() => {
    if (data?.connection && data.addon.active) load();
  }, [data?.connection, data?.addon.active, load]);
  const active = !!room && (room.lead_busy || room.roster.some((m) => m.working));
  usePoll(!!room, load, active ? 2500 : 10000);
  useEffect(() => {
    if (room && room.messages.length !== count.current) {
      count.current = room.messages.length;
      feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: "smooth" });
    }
  }, [room]);

  async function send(value?: string) {
    const msg = (value ?? text).trim();
    if (!msg) return;
    setSending(true);
    setError(null);
    try {
      await api(`${base}/chat`, { method: "POST", body: { text: msg } });
      setText("");
      await load();
    } catch (err) {
      setError(errorText(err, t("error")));
    } finally {
      setSending(false);
    }
  }

  const href = (p: NonNullable<Msg["payload"]>) =>
    p.link === "video" ? `/t/${tenantId}/youtube/videos/${p.video_id}${p.tab ? `?tab=${p.tab}` : ""}` : `/t/${tenantId}/youtube/${p.link}`;

  return (
    <StudioGate tenantId={tenantId} data={data}>
      {room && (
        <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
          <section className="flex min-h-[560px] flex-col rounded-2xl border border-border bg-surface" aria-label={t("chat")}>
            <div className="flex items-center gap-3 border-b border-border px-4 py-3">
              <Face agent="yt_lead" size={38} working={room.lead_busy} />
              <div>
                <p className="text-sm font-semibold">{t("names.yt_lead")}</p>
                <p className="text-xs text-muted">{room.lead_busy ? t("thinking") : t("leadHint")}</p>
              </div>
            </div>
            <div ref={feed} className="flex max-h-[62vh] flex-1 flex-col gap-3 overflow-y-auto p-4" aria-live="polite">
              {room.messages.length === 0 && <p className="text-sm text-muted">{t("empty")}</p>}
              {room.messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.message_id} className="max-w-xl self-end whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm text-accent-text" dir="auto">{m.text}</div>
                ) : (
                  <div key={m.message_id} className="ls-slide flex max-w-2xl gap-2">
                    <Face agent={m.agent ?? "yt_lead"} size={30} />
                    <div className="min-w-0 space-y-1">
                      <p className="text-[11px] text-muted">
                        <b style={{ color: YT_AGENTS[m.agent ?? "yt_lead"]?.color }}>{t(`names.${m.agent ?? "yt_lead"}`)}</b> · {formatDateTime(m.created_at).slice(-5)}
                      </p>
                      <p className="whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-bg px-3 py-2 text-sm" dir="auto">{m.text}</p>
                      {m.payload?.link && (
                        <Link href={href(m.payload)} className="inline-block rounded-full border border-border px-3 py-1 text-xs hover:border-accent">
                          {t(`open.${m.payload.link}`)} →
                        </Link>
                      )}
                    </div>
                  </div>
                ),
              )}
              {room.lead_busy && (
                <div className="flex items-center gap-2 text-xs text-muted">
                  <Face agent="yt_lead" size={24} working /> <span className="ls-type overflow-hidden whitespace-nowrap">{t("thinking")}</span>
                </div>
              )}
            </div>
            {canWork && (
              <form onSubmit={(e) => { e.preventDefault(); send(); }} className="space-y-2 border-t border-border p-3">
                <div className="flex flex-wrap gap-1.5">
                  {(["s1", "s2", "s3", "s4"] as const).map((k) => (
                    <button key={k} type="button" disabled={sending || room.lead_busy} onClick={() => send(t(`suggest.${k}`))}
                      className="rounded-full border border-border px-3 py-1 text-xs text-muted hover:border-accent hover:text-text disabled:opacity-50">
                      {t(`suggest.${k}`)}
                    </button>
                  ))}
                </div>
                <div className="flex gap-2">
                  <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={2000} placeholder={t("placeholder")} dir="auto"
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                    className="min-w-0 flex-1 resize-none rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none" />
                  <button type="submit" disabled={sending || room.lead_busy || !text.trim()} className="self-end rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text disabled:opacity-50">
                    {t("send")}
                  </button>
                </div>
                {error && <p className="text-sm text-danger">{error}</p>}
              </form>
            )}
          </section>

          <aside className="space-y-2" aria-label={t("roster")}>
            <h2 className="px-1 text-xs font-semibold uppercase tracking-wide text-muted">{t("roster")}</h2>
            {room.roster.map((m) => {
              const working = m.working || (m.agent === "yt_lead" && room.lead_busy);
              return (
                <div key={m.agent} className={`ch-card relative flex items-center gap-3 overflow-hidden rounded-xl border bg-surface p-3 transition ${working ? "border-transparent" : "border-border"}`}
                  style={{ ["--ch-glow" as string]: YT_AGENTS[m.agent]?.color, boxShadow: working ? `0 0 0 1px ${YT_AGENTS[m.agent]?.color}` : undefined } as CSSProperties}>
                  <Face agent={m.agent} size={36} working={working} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{t(`names.${m.agent}`)}</p>
                    <p className="truncate text-[11px] text-muted">{t(`roles.${m.agent}`)}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${working ? "bg-success/15 text-success" : "bg-bg text-muted"}`}>
                    {working ? t("working") : t("ready")}
                  </span>
                </div>
              );
            })}
          </aside>
        </div>
      )}
    </StudioGate>
  );
}
