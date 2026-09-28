"use client";

// Home page: one card per connected channel, with the platform's logo in a moving ring of its
// own colours, the page name, the latest numbers and a follower curve that draws itself.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { type CSSProperties, useCallback, useEffect, useId, useRef, useState } from "react";

import { BRANDS, BrandLogo } from "@/lib/brand-icons";
import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { ChannelCard } from "@/lib/types";

const POLL_MS = 5 * 60_000;

export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1).replace(/\.0$/, "")}M`;
  if (abs >= 100_000) return `${Math.round(n / 1000)}K`;
  return n.toLocaleString("en-US").replaceAll(",", " ");
}

/** Counts up from 0 to the value once, so a fresh number feels alive (skipped with reduced motion). */
function useCountUp(value: number | null): number | null {
  const [shown, setShown] = useState(value);
  const from = useRef(0);
  useEffect(() => {
    if (value === null) return setShown(null);
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return setShown(value);
    const start = performance.now();
    const base = from.current;
    let frame = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / 900);
      const eased = 1 - Math.pow(1 - k, 3);
      setShown(Math.round(base + (value - base) * eased));
      if (k < 1) frame = requestAnimationFrame(step);
      else from.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return shown;
}

function LogoOrb({ channel, live }: { channel: string; live: boolean }) {
  const ring = BRANDS[channel]?.ring ?? ["var(--accent)", "var(--accent)"];
  const style = {
    "--ch-ring": `conic-gradient(from 0deg, ${ring.join(", ")})`,
    "--ch-glow": BRANDS[channel]?.color ?? "var(--accent)",
  } as CSSProperties;
  return (
    <div className="relative grid h-14 w-14 shrink-0 place-items-center" style={style}>
      <span className={`ch-ring absolute inset-0 rounded-full ${live ? "" : "ch-still"}`} aria-hidden="true" />
      <span className="absolute inset-[3px] rounded-full bg-surface" aria-hidden="true" />
      {live && <span className="ch-ping absolute inset-0 rounded-full" aria-hidden="true" />}
      <span className="ch-float relative">
        <BrandLogo channel={channel} size={26} />
      </span>
    </div>
  );
}

function Sparkline({ points, color }: { points: { day: string; followers: number | null }[]; color: string }) {
  const id = useId().replaceAll(":", "");
  const values = points.map((p) => p.followers).filter((v): v is number => v !== null);
  if (values.length < 2) return <div className="h-12" />;
  const w = 220, h = 48, pad = 4;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const xy = values.map((v, i) => [pad + (i * (w - 2 * pad)) / (values.length - 1), h - pad - ((v - min) / span) * (h - 2 * pad)] as const);
  const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const [lx, ly] = xy[xy.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-12 w-full" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={`f${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.35" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${lx.toFixed(1)} ${h} L${pad} ${h} Z`} fill={`url(#f${id})`} className="ch-fade" />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" pathLength={1} className="ch-draw" vectorEffect="non-scaling-stroke" />
      <circle cx={lx} cy={ly} r="3" fill={color} className="ch-dot" />
    </svg>
  );
}

function Growth({ value, label }: { value: number | null; label: string }) {
  if (value === null) return null;
  const tone = value > 0 ? "text-success" : value < 0 ? "text-danger" : "text-muted";
  return (
    <span className={`text-xs font-medium tabular-nums ${tone}`}>
      {value > 0 ? "▲ +" : value < 0 ? "▼ " : ""}
      {formatCount(value)} <span className="font-normal text-muted">{label}</span>
    </span>
  );
}

function Card({ c, tenantId }: { c: ChannelCard; tenantId: string }) {
  const t = useTranslations("channels");
  const followers = useCountUp(c.followers);
  const brand = BRANDS[c.channel];
  const perPost = (n: number | null) => (n !== null && c.recent ? Math.round((n / c.recent) * 10) / 10 : null);
  const isYt = c.channel === "youtube";
  const stats: [string, string][] = isYt
    ? [[t("views"), formatCount(c.views)], [t("videos"), formatCount(c.posts)]]
    : [[t("posts"), formatCount(c.posts)]];
  if (!isYt && c.recent) {
    stats.push([t("likesPerPost"), formatCount(perPost(c.likes))], [t("commentsPerPost"), formatCount(perPost(c.comments))]);
  }
  if (c.engagement_rate !== null) stats.push([t("engagement"), `${c.engagement_rate}%`]);
  const inner = (
    <>
      <div className="flex items-start gap-3">
        <LogoOrb channel={c.channel} live={c.status === "active" && !c.paused} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {c.avatar && (
              <img src={c.avatar} alt="" className="h-5 w-5 rounded-full object-cover" onError={(e) => (e.currentTarget.style.display = "none")} />
            )}
            <p className="truncate text-sm font-semibold">{c.name}</p>
          </div>
          <p className="truncate text-xs text-muted">
            {brand?.name ?? c.channel}
            {c.extra.username ? ` · @${c.extra.username}` : c.extra.handle ? ` · ${c.extra.handle}` : ""}
          </p>
        </div>
        <span
          className={`mt-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
            c.paused ? "bg-accent/15 text-accent" : c.status === "active" ? "bg-success/15 text-success" : "bg-danger/15 text-danger"
          }`}
        >
          {c.paused ? t("paused") : c.status === "active" ? t("live") : t("problem")}
        </span>
      </div>

      {c.followers === null ? (
        <p className="py-5 text-sm text-muted">{c.paused ? t("pausedNoData") : t("noData")}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-x-3">
            <div>
              <p className="text-3xl font-semibold tabular-nums leading-none">{formatCount(followers)}</p>
              <p className="mt-1 text-xs text-muted">{isYt ? t("subscribers") : t("followers")}</p>
            </div>
            <div className="flex flex-col items-end gap-0.5">
              <Growth value={c.growth_7d} label={t("week")} />
              <Growth value={c.growth_30d} label={t("month")} />
            </div>
          </div>
          <Sparkline points={c.series} color={brand?.color ?? "var(--accent)"} />
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-4">
            {stats.map(([k, v]) => (
              <div key={k}>
                <dt className="text-muted">{k}</dt>
                <dd className="font-medium tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
          {c.collected_at && <p className="text-[11px] text-muted">{t("updated", { at: formatDateTime(c.collected_at) })}</p>}
        </>
      )}
    </>
  );
  const cls = "ch-card group relative block space-y-3 overflow-hidden rounded-xl border border-border bg-surface p-4 transition hover:-translate-y-0.5";
  const style = { "--ch-glow": brand?.color ?? "var(--accent)" } as CSSProperties;
  if (isYt) {
    return <Link href={`/t/${tenantId}/youtube`} className={cls} style={style}>{inner}</Link>;
  }
  return c.url ? (
    <a href={c.url} target="_blank" rel="noreferrer" className={cls} style={style}>{inner}</a>
  ) : (
    <div className={cls} style={style}>{inner}</div>
  );
}

export function ChannelCards({ tenantId }: { tenantId: string }) {
  const t = useTranslations("channels");
  const [cards, setCards] = useState<ChannelCard[] | null>(null);
  const load = useCallback(async () => {
    try {
      setCards(await api<ChannelCard[]>(`/tenants/${tenantId}/channels`));
    } catch {
      setCards((prev) => prev ?? []);
    }
  }, [tenantId]);
  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  if (cards === null) return null;
  if (cards.length === 0) {
    return (
      <Link href={`/t/${tenantId}/connections`} className="flex items-center gap-4 rounded-xl border border-dashed border-border bg-surface p-4 text-sm hover:border-accent">
        <span className="flex -space-x-2">
          {["instagram", "facebook", "youtube"].map((ch) => (
            <span key={ch} className="grid h-9 w-9 place-items-center rounded-full border border-border bg-bg"><BrandLogo channel={ch} size={18} /></span>
          ))}
        </span>
        <span>
          <b className="block font-semibold">{t("emptyTitle")}</b>
          <span className="text-muted">{t("emptyHint")}</span>
        </span>
      </Link>
    );
  }
  return (
    <section aria-label={t("title")} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map((c) => (
        <Card key={c.connection_id} c={c} tenantId={tenantId} />
      ))}
    </section>
  );
}
