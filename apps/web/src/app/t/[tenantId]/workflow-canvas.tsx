"use client";

// The team's work drawn live as a workflow: every task (a post, the market research, the morning
// report) is a chain of steps; the running step glows, and pulses of light travel along the links.
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";

import { AGENT_COLOR } from "@/lib/agents";
import type { LiveInfo, LiveJob } from "@/lib/types";

const NEON = "#3EE89A";
const W = 220; // node size in canvas units
const H = 104;

type Status = "pending" | "running" | "done" | "failed" | "waiting";
type FlowNode = { key: string; agent: string | null; status: Status; note?: string; trigger?: boolean };

const ICON: Record<string, string> = {
  trigger_post: "M4 5h16v14H4zm4 4.5a1.5 1.5 0 1 0 0-.01M20 15l-5-5L6 19",
  trigger_market: "M12 7v5l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  trigger_briefing: "M12 7v5l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  photos: "M4 5h16v14H4zm4 4.5a1.5 1.5 0 1 0 0-.01M20 15l-5-5L6 19",
  copy: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
  guard: "M12 3 5 6v5c0 4.4 3 8.3 7 9.5 4-1.2 7-5.1 7-9.5V6zM9 12l2 2 4-4",
  approval: "M6 17v-6a6 6 0 1 1 12 0v6l1.5 2h-15zM10 21a2 2 0 0 0 4 0",
  publish: "M3 11 21 3l-6 18-3.5-7z",
  competitors: "M4 4h16v16H4zM9 9a3 3 0 1 0 6 0 3 3 0 0 0-6 0m8.5-3.5v.01",
  own_page: "M21 12a8 8 0 0 1-11.8 7L4 20l1.1-4.6A8 8 0 1 1 21 12",
  web: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18m-9 9h18M12 3c2.5 2.5 3.5 5.5 3.5 9S14.5 18.5 12 21c-2.5-2.5-3.5-5.5-3.5-9S9.5 5.5 12 3",
  analyse: "M4 19V9m5 10V5m5 14v-7m5 7V9",
  deliver: "M4 4h16v12H7l-3 3zM8 9h8M8 12h5",
  facts: "M5 4h14v16H5zM8 8h8M8 12h8M8 16h5",
  read_market: "M4 19V9m5 10V5m5 14v-7m5 7V9",
  plan: "M9 11l2 2 4-4M5 4h14v16H5z",
};

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(960);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function nodesOf(job: LiveJob): FlowNode[] {
  const trigger: FlowNode = { key: `trigger_${job.kind}`, agent: job.kind === "post" ? "team_lead" : job.kind === "market" ? "market_researcher" : "team_lead", status: "done", trigger: true };
  return [trigger, ...job.steps.map((s) => ({ key: s.key, agent: s.agent, status: s.status as Status, note: s.note }))];
}

/** Snake layout: rows of `cols` nodes, every other row right-to-left, so the flow winds down. */
function layout(n: number, cols: number, width: number) {
  const gap = cols > 1 ? (width - 40 - cols * W) / (cols - 1) : 0;
  const pos = Array.from({ length: n }, (_, i) => {
    const row = Math.floor(i / cols);
    const idx = i % cols;
    const col = row % 2 === 0 ? idx : cols - 1 - idx;
    return { x: cols > 1 ? 20 + col * (W + gap) : (width - W) / 2, y: 24 + row * (H + 64), row };
  });
  const height = 24 + (Math.ceil(n / cols) - 1) * (H + 64) + H + 24;
  return { pos, height };
}

function edgePath(a: { x: number; y: number; row: number }, b: { x: number; y: number; row: number }) {
  if (a.row !== b.row) {
    const x1 = a.x + W / 2, y1 = a.y + H, x2 = b.x + W / 2, y2 = b.y;
    const my = (y1 + y2) / 2;
    return `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`;
  }
  const leftToRight = b.x > a.x;
  const x1 = leftToRight ? a.x + W : a.x, x2 = leftToRight ? b.x : b.x + W, y = a.y + H / 2;
  const d = (x2 - x1) / 2;
  return `M${x1},${y} C${x1 + d},${y} ${x2 - d},${y} ${x2},${y}`;
}

function NodeCard({ node, thumb, label, agentName, statusLabel }: { node: FlowNode; thumb?: string | null; label: string; agentName: string; statusLabel: string }) {
  const color = node.agent ? AGENT_COLOR[node.agent] ?? NEON : AGENT_COLOR.approval;
  const tone = node.status === "done" ? NEON : node.status === "failed" ? "#FF5C5C" : node.status === "pending" ? "#26362f" : color;
  const live = node.status === "running" || node.status === "waiting";
  return (
    <div
      className={`wf-node relative flex h-full flex-col gap-1.5 overflow-hidden rounded-2xl p-3 ${live ? "wf-live" : ""} ${node.status === "pending" ? "opacity-55" : ""}`}
      style={{ ["--c" as string]: tone, borderColor: tone }}
    >
      {live && <span className="wf-sweep pointer-events-none absolute inset-0" />}
      <div className="flex items-center gap-2">
        <span className="relative grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-lg" style={{ background: color }}>
          {node.trigger && thumb ? (
            <img src={thumb} alt="" className="h-full w-full object-cover" />
          ) : (
            <svg viewBox="0 0 24 24" className={`h-[18px] w-[18px] ${live ? "wf-icon-live" : ""}`} fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d={ICON[node.key] ?? ICON.plan} />
            </svg>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold leading-4 text-white">{label}</p>
          <p className="truncate text-[11px] leading-4 text-white/50">{agentName}</p>
        </div>
      </div>
      <div className="mt-auto flex items-center gap-1.5 text-[11px]">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${live ? "wf-dot" : ""}`} style={{ background: tone }} />
        <span className="shrink-0" style={{ color: node.status === "pending" ? "rgba(255,255,255,.45)" : tone }}>{statusLabel}</span>
        {node.note && <span className="truncate text-white/60">· {node.note}</span>}
        {live && !node.note && <span className="wf-skeleton h-1.5 flex-1 rounded-full" />}
      </div>
    </div>
  );
}

function Flow({ job, width }: { job: LiveJob; width: number }) {
  const t = useTranslations("team");
  const nodes = nodesOf(job);
  const cols = width < 560 ? 1 : width < 900 ? 2 : 3;
  const vw = cols === 1 ? 300 : cols === 2 ? 640 : 960;
  const { pos, height } = layout(nodes.length, cols, vw);
  return (
    <svg viewBox={`0 0 ${vw} ${height}`} className="block w-full" role="img" aria-label={job.title}>
      <defs>
        <filter id="wf-glow" filterUnits="userSpaceOnUse" x={0} y={0} width={vw} height={height}>
          <feGaussianBlur stdDeviation="3.5" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {nodes.slice(1).map((n, i) => {
        const from = nodes[i];
        const d = edgePath(pos[i], pos[i + 1]);
        const flowing = from.status === "done" && (n.status === "running" || n.status === "waiting");
        const lit = from.status === "done" && (n.status === "done" || flowing);
        const failed = n.status === "failed";
        return (
          <g key={`e${i}`}>
            <path d={d} fill="none" stroke="#1f2e28" strokeWidth={3} />
            {lit && <path d={d} fill="none" stroke={NEON} strokeWidth={2} filter="url(#wf-glow)" opacity={0.9} />}
            {failed && <path d={d} fill="none" stroke="#FF5C5C" strokeWidth={2} strokeDasharray="4 6" opacity={0.8} />}
            {flowing && (
              <>
                <path d={d} fill="none" stroke="#fff" strokeWidth={2} strokeDasharray="3 14" className="wf-flow" opacity={0.8} />
                {[0, 0.55].map((delay) => (
                  <circle key={delay} r={4.5} fill={NEON} filter="url(#wf-glow)">
                    <animateMotion dur="1.4s" begin={`${delay}s`} repeatCount="indefinite" path={d} />
                  </circle>
                ))}
              </>
            )}
            {!lit && !failed && <path d={d} fill="none" stroke="#2c4038" strokeWidth={1.5} strokeDasharray="2 7" />}
          </g>
        );
      })}
      {nodes.map((n, i) => (
        <foreignObject key={n.key + i} x={pos[i].x} y={pos[i].y} width={W} height={H}>
          <NodeCard
            node={n}
            thumb={job.thumb_url}
            label={t(`flow.steps.${n.key}`)}
            agentName={n.agent ? t(`agents.${n.agent}`) : t("flow.you")}
            statusLabel={n.trigger ? t(`flow.triggerStatus.${job.kind}`) : t(`flow.status.${n.status}`)}
          />
        </foreignObject>
      ))}
    </svg>
  );
}

function IdleTeam({ live, width }: { live: LiveInfo | null; width: number }) {
  const t = useTranslations("team");
  const agents = ["market_researcher", "media_analyst", "copywriter", "brand_guardian", "visual_editor", "publisher"];
  const state = Object.fromEntries((live?.agents ?? []).map((a) => [a.agent, a]));
  const narrow = width < 560;
  const vw = narrow ? 320 : 960, vh = narrow ? 420 : 300;
  const lead = narrow ? { x: 160, y: 60 } : { x: 480, y: 70 };
  const spots = agents.map((_, i) =>
    narrow ? { x: 80 + (i % 2) * 160, y: 170 + Math.floor(i / 2) * 90 } : { x: 90 + i * 156, y: 225 },
  );
  return (
    <svg viewBox={`0 0 ${vw} ${vh}`} className="block w-full" role="img" aria-label={t("flow.idle")}>
      <defs>
        <filter id="wf-glow2" filterUnits="userSpaceOnUse" x={0} y={0} width={vw} height={vh}>
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {spots.map((p, i) => {
        const d = `M${lead.x},${lead.y + 26} C${lead.x},${(lead.y + p.y) / 2} ${p.x},${(lead.y + p.y) / 2} ${p.x},${p.y - 26}`;
        const working = state[agents[i]]?.state === "working";
        return (
          <g key={agents[i]}>
            <path d={d} fill="none" stroke={working ? NEON : "#22352d"} strokeWidth={working ? 2 : 1.5} filter={working ? "url(#wf-glow2)" : undefined} strokeDasharray={working ? undefined : "2 6"} />
            <circle r={3} fill={AGENT_COLOR[agents[i]]} opacity={0.9} filter="url(#wf-glow2)">
              <animateMotion dur={`${3.2 + i * 0.35}s`} repeatCount="indefinite" path={d} />
            </circle>
          </g>
        );
      })}
      {[{ key: "team_lead", ...lead }, ...agents.map((a, i) => ({ key: a, ...spots[i] }))].map((n) => (
        <g key={n.key} transform={`translate(${n.x},${n.y})`}>
          <circle r={26} fill="#0c1814" stroke={AGENT_COLOR[n.key]} strokeWidth={2} className={state[n.key]?.state === "working" ? "wf-breathe-fast" : "wf-breathe"} />
          <circle r={9} fill={AGENT_COLOR[n.key]} />
          <text y={44} textAnchor="middle" className="fill-white/80 text-[12px] font-medium">{t(`agents.${n.key}`)}</text>
        </g>
      ))}
    </svg>
  );
}

export function WorkflowCanvas({ live }: { live: LiveInfo | null }) {
  const t = useTranslations("team");
  const [ref, width] = useWidth<HTMLDivElement>();
  const jobs = useMemo(() => [...(live?.jobs ?? [])].reverse(), [live]); // newest first
  const [picked, setPicked] = useState<string | null>(null);
  const running = jobs.find((j) => j.status === "running");
  const job = jobs.find((j) => j.task_id === picked) ?? running ?? jobs[0] ?? null;
  const agents = Object.fromEntries((live?.agents ?? []).map((a) => [a.agent, a]));

  return (
    <section className="wf-stage overflow-hidden rounded-2xl border" aria-label={t("teamTitle")}>
      <div className="flex flex-wrap items-center gap-2 px-4 pt-3">
        <h2 className="mr-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-white/70">
          <span className="wf-dot h-2 w-2 rounded-full" style={{ background: NEON }} /> {t("teamTitle")}
        </h2>
        {jobs.slice(0, 6).map((j) => {
          const active = job?.task_id === j.task_id;
          return (
            <button
              key={j.task_id}
              type="button"
              onClick={() => setPicked(j.task_id)}
              className={`flex max-w-[220px] items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition ${
                active ? "border-[#3EE89A] bg-[#3EE89A]/10 text-white" : "border-white/10 text-white/60 hover:text-white"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${j.status === "running" ? "wf-dot" : ""}`}
                style={{ background: j.status === "failed" ? "#FF5C5C" : j.status === "running" || j.status === "waiting_approval" ? "#F2B01E" : NEON }}
              />
              <span className="truncate">{j.title}</span>
            </button>
          );
        })}
      </div>

      <div ref={ref} className="px-2 pb-2 pt-1">
        {job ? (
          <>
            <Flow key={job.task_id} job={job} width={width} />
            <p className="px-2 pb-1 text-[11px] text-white/45">
              {t(`flow.kind.${job.kind}`)} · {t(`flow.task.${job.status}`)}
            </p>
          </>
        ) : (
          <>
            <IdleTeam live={live} width={width} />
            <p className="px-2 pb-2 text-center text-xs text-white/55">{t("flow.idle")}</p>
          </>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-white/10 px-4 py-2.5">
        <span className="text-[11px] text-white/50">{t("studio.moreTeam")}</span>
        {["market_researcher", "visual_editor"].map((k) => (
          <span key={k} className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] text-white/80 ${agents[k]?.state === "working" ? "border-[#3EE89A]" : "border-white/15"}`}>
            <span className="h-2 w-2 rounded-full" style={{ background: AGENT_COLOR[k] }} />
            {t(`agents.${k}`)}
            {k === "market_researcher" && <span className="text-white/45">· {t("studio.researchSchedule")}</span>}
          </span>
        ))}
        {(["planner", "visual_designer", "community", "analyst", "cmo", "ads", "video"] as const).map((k) => (
          <span key={k} className="flex items-center gap-1.5 rounded-full border border-dashed border-white/15 px-2 py-0.5 text-[11px] text-white/45" title={t(`studio.coming.${k}.hint`)}>
            {t(`studio.coming.${k}.name`)} <span className="rounded bg-white/5 px-1 text-[10px]">{t("studio.soon")}</span>
          </span>
        ))}
      </div>
    </section>
  );
}
