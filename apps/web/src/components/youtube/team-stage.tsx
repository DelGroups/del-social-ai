"use client";

// The YouTube team, live, on the studio's home: the Channel Manager on top, the team below it,
// joined by lines that carry moving light while someone works. Talk to the manager right here.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type CSSProperties, useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client-api";

import { errorText, usePoll } from "./common";
import { YT_AGENTS } from "./team";

type Member = { agent: string; working: boolean; last_at: string | null };
type Room = { messages: { role: string; agent: string | null; text: string }[]; roster: Member[]; lead_busy: boolean };

function Node({ agent, working, label, sub }: { agent: string; working: boolean; label: string; sub: string }) {
  const a = YT_AGENTS[agent] ?? YT_AGENTS.yt_lead;
  return (
    <div className={`wf-node relative flex items-center gap-2.5 overflow-hidden px-3 py-2.5 ${working ? "wf-live" : ""}`}
      style={{ ["--c" as string]: a.color, borderColor: working ? a.color : "var(--node-line)" } as CSSProperties}>
      {working && <span className="wf-sweep pointer-events-none absolute inset-0" />}
      <span className={`relative grid h-9 w-9 shrink-0 place-items-center rounded-full text-white ${working ? "wf-icon-live" : ""}`}
        style={{ background: a.color, boxShadow: working ? `0 0 18px ${a.color}` : undefined }}>
        <svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d={a.icon} />
        </svg>
      </span>
      <span className="relative min-w-0">
        <span className="block truncate text-[13px] font-semibold" style={{ color: "var(--stage-text)" }}>{label}</span>
        <span className="flex items-center gap-1 truncate text-[11px]" style={{ color: working ? a.color : "var(--stage-muted)" }}>
          {working && <span className="wf-dot inline-block h-1.5 w-1.5 rounded-full" style={{ background: a.color }} />}
          {sub}
        </span>
      </span>
    </div>
  );
}

export function TeamStage({ tenantId, canWork }: { tenantId: string; canWork: boolean }) {
  const t = useTranslations("yt.team");
  const router = useRouter();
  const [room, setRoom] = useState<Room | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/tenants/${tenantId}/youtube/team`;
  const load = useCallback(async () => {
    try {
      setRoom(await api<Room>(base));
    } catch {
      /* keep */
    }
  }, [base]);
  useEffect(() => {
    load();
  }, [load]);
  const active = !!room && (room.lead_busy || room.roster.some((m) => m.working));
  usePoll(true, load, active ? 3000 : 12000);

  async function send() {
    const msg = text.trim();
    if (!msg) return;
    setBusy(true);
    setError(null);
    try {
      await api(`${base}/chat`, { method: "POST", body: { text: msg } });
      router.push(`/t/${tenantId}/youtube/team`);
    } catch (err) {
      setError(errorText(err, t("error")));
      setBusy(false);
    }
  }

  if (!room) return <div className="wf-skeleton h-56 rounded-2xl" />;
  const team = room.roster.filter((m) => m.agent !== "yt_lead");
  const lastLead = [...room.messages].reverse().find((m) => m.agent === "yt_lead");
  const anyWorking = team.some((m) => m.working) || room.lead_busy;
  return (
    <section className="wf-stage space-y-4 overflow-hidden rounded-2xl border p-4" aria-label={t("roster")}>
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--stage-muted)" }}>
          <span className={`inline-block h-2 w-2 rounded-full ${anyWorking ? "wf-dot" : ""}`} style={{ background: anyWorking ? "var(--flow)" : "var(--stage-muted)" }} />
          {t("live")}
        </p>
        <Link href={`/t/${tenantId}/youtube/team`} className="text-xs underline" style={{ color: "var(--stage-muted)" }}>{t("openTeam")} →</Link>
      </div>

      <div className="mx-auto w-full max-w-xs">
        <Node agent="yt_lead" working={room.lead_busy} label={t("names.yt_lead")} sub={room.lead_busy ? t("thinking") : t("roles.yt_lead")} />
      </div>
      {/* The links: a trunk from the manager to a bus, and one drop to every member; light runs along them while work goes on */}
      <div className="relative hidden h-6 md:block" aria-hidden="true">
        <span className={`absolute left-1/2 top-0 h-3 w-0.5 -translate-x-1/2 ${anyWorking ? "ls-wire-live" : "ls-wire"}`} style={{ ["--accent" as string]: "var(--flow)" } as CSSProperties} />
        <span className={`absolute left-[7%] right-[7%] top-3 h-0.5 ${anyWorking ? "ls-wire-live" : "ls-wire"}`} style={{ ["--accent" as string]: "var(--flow)" } as CSSProperties} />
        {team.map((m, i) => (
          <span key={m.agent} className={`absolute top-3 h-3 w-0.5 ${m.working ? "ls-wire-live" : "ls-wire"}`}
            style={{ left: `${7 + (86 / (team.length - 1)) * i}%`, ["--accent" as string]: YT_AGENTS[m.agent]?.color } as CSSProperties} />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
        {team.map((m) => (
          <Node key={m.agent} agent={m.agent} working={m.working} label={t(`names.${m.agent}`)} sub={m.working ? t("working") : t(`roles.${m.agent}`)} />
        ))}
      </div>

      {canWork && (
        <div className="space-y-2 border-t pt-3" style={{ borderColor: "var(--node-line)" }}>
          {lastLead && (
            <p className="line-clamp-2 text-xs" style={{ color: "var(--stage-muted)" }} dir="auto">
              <b style={{ color: YT_AGENTS.yt_lead.color }}>{t("names.yt_lead")}:</b> {lastLead.text}
            </p>
          )}
          <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2">
            <input value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} placeholder={t("placeholder")} dir="auto"
              className="min-w-0 flex-1 rounded-md border bg-transparent px-3 py-2 text-sm focus:outline-none"
              style={{ borderColor: "var(--node-line)", color: "var(--stage-text)" }} />
            <button type="submit" disabled={busy || room.lead_busy || !text.trim()} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text disabled:opacity-50">
              {t("send")}
            </button>
          </form>
          {error && <p className="text-sm text-danger">{error}</p>}
        </div>
      )}
    </section>
  );
}
