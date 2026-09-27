"use client";

// The live production line: every task moves across the team as it is worked on, and each agent
// shows what it is doing right now with its own small animation.
import { useTranslations } from "next-intl";

import type { LiveInfo, LiveJob } from "@/lib/types";

export const AGENT_COLOR: Record<string, string> = {
  team_lead: "#6C5CE7",
  media_analyst: "#0E9F9F",
  copywriter: "#E0752D",
  brand_guardian: "#2F8F6B",
  approval: "#F2B01E",
  publisher: "#3B6FD8",
  channels: "#C2549B",
  visual_editor: "#C2549B",
};

// Stations of the line, left to right. "approval" is you; "channels" is Instagram + Facebook.
const STATIONS = ["team_lead", "media_analyst", "copywriter", "brand_guardian", "approval", "publisher", "channels"] as const;
type Station = (typeof STATIONS)[number];
const STEP_STATION: Record<string, Station> = {
  photos: "media_analyst",
  copy: "copywriter",
  guard: "brand_guardian",
  approval: "approval",
  publish: "publisher",
};

// Members who are part of the team plan but not built yet (docs/agent-team.md, build order agreed 2026-09-27)
const COMING = ["planner", "visual_designer", "community", "analyst", "cmo", "ads", "video"] as const;

/** Where a job is on the line, and whether something is happening to it there. */
export function jobPlace(job: LiveJob): { index: number; mode: "active" | "waiting" | "idle" | "failed" | "done" } {
  if (job.status === "failed" || job.steps.some((s) => s.status === "failed")) {
    const failed = job.steps.find((s) => s.status === "failed");
    return { index: failed ? STATIONS.indexOf(STEP_STATION[failed.key]) : 0, mode: "failed" };
  }
  const current = job.steps.find((s) => s.status !== "done");
  if (!current) return { index: STATIONS.length - 1, mode: "done" };
  if (job.steps.every((s) => s.status === "pending")) return { index: 0, mode: "active" };
  const index = STATIONS.indexOf(STEP_STATION[current.key] ?? "team_lead");
  return { index, mode: current.status === "running" ? "active" : current.status === "waiting" ? "waiting" : "idle" };
}

function StationArt({ station, busy, thumb }: { station: Station; busy: boolean; thumb?: string | null }) {
  // Small animated scene per agent; still (but visible) when idle
  switch (station) {
    case "team_lead":
      return (
        <div className="flex h-full items-center justify-center gap-1">
          {[0, 1, 2].map((i) => (
            <span key={i} className={`h-1.5 w-1.5 rounded-full bg-white ${busy ? "ls-bounce" : "opacity-60"}`} style={{ animationDelay: `${i * 0.15}s` }} />
          ))}
        </div>
      );
    case "media_analyst":
      return (
        <div className="relative h-full w-full overflow-hidden rounded-md bg-white/15">
          {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover opacity-90" /> : <PhotoGlyph />}
          {busy && <span className="ls-scan absolute inset-x-0 h-3" />}
          {busy && <span className="ls-corners absolute inset-1 rounded-sm" />}
        </div>
      );
    case "copywriter":
      return (
        <div className="flex h-full w-full flex-col justify-center gap-1 px-1.5">
          {[0.9, 0.7, 0.8].map((w, i) => (
            <span key={i} className="h-1 rounded-full bg-white/30">
              <span className={`block h-full rounded-full bg-white ${busy ? "ls-type" : ""}`} style={{ width: busy ? undefined : `${w * 100}%`, animationDelay: `${i * 0.5}s` }} />
            </span>
          ))}
        </div>
      );
    case "brand_guardian":
      return (
        <svg viewBox="0 0 24 24" className="h-full w-full p-0.5" aria-hidden="true">
          <path d="M12 2 4 5v6c0 5 3.4 9.5 8 11 4.6-1.5 8-6 8-11V5l-8-3Z" fill="rgba(255,255,255,.18)" stroke="#fff" strokeWidth="1.5" />
          <path d="m8.5 12 2.5 2.5 4.5-5" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={busy ? "ls-draw" : ""} />
          {busy && <circle cx="12" cy="12" r="10" fill="none" stroke="#fff" strokeWidth="1" className="ls-ping" />}
        </svg>
      );
    case "approval":
      return (
        <svg viewBox="0 0 24 24" className={`h-full w-full p-0.5 ${busy ? "ls-ring" : ""}`} aria-hidden="true">
          <path d="M6 17V11a6 6 0 1 1 12 0v6l1.5 2h-15L6 17Z" fill="rgba(255,255,255,.2)" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M10 21a2 2 0 0 0 4 0" stroke="#fff" strokeWidth="1.5" fill="none" />
        </svg>
      );
    case "publisher":
      return (
        <div className="relative h-full w-full overflow-hidden">
          <svg viewBox="0 0 24 24" className={`absolute inset-0 h-full w-full p-0.5 ${busy ? "ls-fly" : ""}`} aria-hidden="true">
            <path d="M3 11 21 3l-6 18-3.5-7L3 11Z" fill="rgba(255,255,255,.25)" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="m11.5 14 4-5" stroke="#fff" strokeWidth="1.5" />
          </svg>
        </div>
      );
    case "channels":
      return (
        <div className="relative flex h-full w-full items-center justify-center">
          <svg viewBox="0 0 24 24" className="h-full w-full p-0.5" aria-hidden="true">
            <rect x="4" y="4" width="16" height="16" rx="5" fill="none" stroke="#fff" strokeWidth="1.6" />
            <circle cx="12" cy="12" r="3.6" fill="none" stroke="#fff" strokeWidth="1.6" />
            <circle cx="16.8" cy="7.2" r="1" fill="#fff" />
          </svg>
          {busy && <span className="ls-burst absolute inset-0 rounded-full" />}
        </div>
      );
  }
}

function PhotoGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-full w-full p-1" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="#fff" strokeWidth="1.5" />
      <circle cx="9" cy="10" r="1.6" fill="#fff" />
      <path d="m4 17 5-5 4 4 3-3 4 4" fill="none" stroke="#fff" strokeWidth="1.5" />
    </svg>
  );
}

export function LiveStudio({ live }: { live: LiveInfo | null }) {
  const t = useTranslations("team");
  const agents = Object.fromEntries((live?.agents ?? []).map((a) => [a.agent, a]));
  const jobs = live?.jobs ?? [];
  const placed = jobs.map((j) => ({ job: j, ...jobPlace(j) }));
  const n = STATIONS.length;

  // A station is busy if its agent is working or a job is being worked on / waits there
  const busy = (s: Station, i: number) =>
    s === "approval"
      ? placed.some((p) => p.index === i && p.mode === "waiting")
      : s === "channels"
        ? placed.some((p) => p.mode === "done" && live && Date.parse(live.now) - Date.parse(p.job.updated_at) < 120_000)
        : agents[s]?.state === "working" || placed.some((p) => p.index === i && p.mode === "active");
  const busyAt = STATIONS.map((s, i) => busy(s, i));
  const countAt = STATIONS.map((_, i) => placed.filter((p) => p.index === i).length);
  const stackAt: number[] = Array(n).fill(0);
  const lanes = Math.max(1, ...countAt);

  function caption(s: Station, i: number): string {
    if (s === "approval") return countAt[i] ? t("studio.waitingYou", { count: countAt[i] }) : t("studio.nothingToApprove");
    if (s === "channels") {
      const today = live?.published.length ?? 0;
      return today ? t("studio.publishedRecent", { count: today }) : t("studio.noPublishYet");
    }
    const a = agents[s];
    if (busyAt[i]) return a?.activity ?? t("studio.working");
    return a?.done_today ? t("doneToday", { count: a.done_today }) : t("studio.ready");
  }

  return (
    <section className="ls-stage overflow-hidden rounded-xl border border-border" aria-label={t("teamTitle")}>
      <div className="flex items-center justify-between px-4 pt-3">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
          <span className="ls-live-dot h-2 w-2 rounded-full bg-success" /> {t("teamTitle")}
        </h2>
        <span className="text-xs text-muted">{t("studio.jobs", { count: jobs.filter((j) => jobPlace(j).mode !== "done").length })}</span>
      </div>

      <div className="overflow-x-auto px-2 pb-3">
        <div className="relative min-w-[760px]">
          {/* Stations */}
          <div className="grid pt-4" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
            {STATIONS.map((s, i) => (
              <div key={s} className="relative flex flex-col items-center px-1 text-center">
                {i < n - 1 && (
                  <span
                    className={`ls-wire absolute top-7 h-0.5 ${busyAt[i + 1] || placed.some((p) => p.index === i + 1 && p.mode !== "done") ? "ls-wire-live" : ""}`}
                    style={{ left: "calc(50% + 30px)", right: "calc(-50% + 30px)" }}
                    aria-hidden="true"
                  />
                )}
                <div
                  className={`relative z-10 grid h-14 w-14 place-items-center rounded-2xl p-2.5 shadow-lg transition-transform duration-500 ${busyAt[i] ? "ls-busy scale-105" : ""}`}
                  style={{ background: AGENT_COLOR[s], ["--ls-c" as string]: AGENT_COLOR[s] }}
                >
                  <StationArt station={s} busy={busyAt[i]} thumb={placed.find((p) => p.index === i)?.job.thumb_url} />
                  {countAt[i] > 0 && s !== "channels" && (
                    <span className="absolute -right-1.5 -top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-text px-1 text-[11px] font-bold text-bg">{countAt[i]}</span>
                  )}
                </div>
                <p className="mt-2 text-xs font-semibold">{t(`studio.station.${s}`)}</p>
                <p key={caption(s, i)} className={`ls-fade mt-0.5 line-clamp-2 min-h-8 max-w-[140px] text-[11px] leading-4 ${busyAt[i] ? "text-text" : "text-muted"}`}>
                  {caption(s, i)}
                </p>
              </div>
            ))}
          </div>

          {/* Jobs travelling along the line */}
          <div className="relative mt-2 border-t border-dashed border-border" style={{ height: lanes * 52 + 12 }}>
            {placed.length === 0 && <p className="pt-4 text-center text-xs text-muted">{t("studio.lineEmpty")}</p>}
            {placed.map(({ job, index, mode }) => {
              const lane = stackAt[index]++;
              const tone = mode === "failed" ? "border-danger" : mode === "waiting" ? "border-accent" : mode === "done" ? "border-success" : "border-border";
              return (
                <div
                  key={job.task_id}
                  className={`ls-job absolute flex w-[124px] items-center gap-1.5 rounded-lg border ${tone} bg-surface p-1 shadow-md`}
                  style={{ left: `calc(${((index + 0.5) / n) * 100}% - 62px)`, top: 8 + lane * 52 }}
                  title={job.title}
                >
                  <span className="relative h-9 w-9 shrink-0 overflow-hidden rounded">
                    {job.thumb_url ? <img src={job.thumb_url} alt="" className="h-full w-full object-cover" /> : <span className="block h-full w-full bg-bg" />}
                    {mode === "active" && <span className="ls-shimmer absolute inset-0" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[11px] font-medium leading-4">{job.title}</span>
                    <span className={`block truncate text-[10px] leading-4 ${mode === "failed" ? "text-danger" : mode === "waiting" ? "text-accent" : "text-muted"}`}>
                      {mode === "done"
                        ? t("studio.jobDone")
                        : mode === "failed"
                          ? t("studio.jobFailed")
                          : job.status === "scheduled" && job.scheduled_at
                            ? t("studio.jobScheduled", { time: new Date(job.scheduled_at).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" }) })
                            : mode === "waiting"
                              ? t("studio.jobWaiting")
                              : t("studio.jobActive")}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* The rest of the team: visible now, working as each one is built */}
      <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2.5">
        <span className="text-[11px] text-muted">{t("studio.moreTeam")}</span>
        <span className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${agents.visual_editor?.state === "working" ? "ls-busy-soft border-accent" : "border-border"}`}>
          <span className="h-2 w-2 rounded-full" style={{ background: AGENT_COLOR.visual_editor }} />
          {t("agents.visual_editor")}
          {agents.visual_editor?.state === "working" && <span className="text-accent">· {t("working")}</span>}
        </span>
        {COMING.map((k) => (
          <span key={k} className="flex items-center gap-1.5 rounded-full border border-dashed border-border px-2 py-0.5 text-[11px] text-muted opacity-70" title={t(`studio.coming.${k}.hint`)}>
            {t(`studio.coming.${k}.name`)} <span className="rounded bg-bg px-1 text-[10px]">{t("studio.soon")}</span>
          </span>
        ))}
      </div>
    </section>
  );
}
