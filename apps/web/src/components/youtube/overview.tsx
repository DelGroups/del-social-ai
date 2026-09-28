"use client";

// YouTube Studio home: the channel with its live numbers, the latest pulse and daily report, the
// big actions (review, ideas, comments) and the latest videos with what the team did for each.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { LogoOrb, Sparkline, formatCount, useCountUp } from "@/components/channel-cards";
import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { YtReport, YtVideo } from "@/lib/youtube";
import { duration } from "@/lib/youtube";

import { CostButton, CreditPill, ReportBody, StudioGate, errorText, useDashboard, usePoll } from "./common";

export function VideoCard({ v, tenantId }: { v: YtVideo; tenantId: string }) {
  const t = useTranslations("yt");
  return (
    <Link href={`/t/${tenantId}/youtube/videos/${v.video_id}`} className="group block space-y-2">
      <div className="relative aspect-video overflow-hidden rounded-lg bg-bg">
        {v.thumbnail_url && <img src={v.thumbnail_url} alt="" className="h-full w-full object-cover transition group-hover:scale-[1.03]" />}
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/80 px-1.5 text-[11px] font-medium text-white">
          {v.is_short ? "Shorts" : duration(v.duration_s)}
        </span>
        {v.privacy && v.privacy !== "public" && (
          <span className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 text-[10px] text-white">{t(`privacy.${v.privacy}`)}</span>
        )}
      </div>
      <p className="line-clamp-2 text-sm font-medium leading-snug group-hover:text-accent" dir="auto">{v.title}</p>
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
        <span className="tabular-nums">{formatCount(v.views)} {t("views")}</span>
        {v.kit && <span className={`rounded-full px-1.5 ${v.kit === "applied" ? "bg-success/15 text-success" : "bg-accent/15 text-accent"}`}>{t(`kit.${v.kit}`)}</span>}
        {v.thumbnail_applied && <span className="rounded-full bg-success/15 px-1.5 text-success">{t("thumbDone")}</span>}
      </div>
    </Link>
  );
}

function ReportCard({ title, report, empty }: { title: string; report: YtReport | null | undefined; empty: string }) {
  return (
    <section className="space-y-3 rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {report && <span className="text-[11px] text-muted">{formatDateTime(report.created_at)}</span>}
      </div>
      {report ? <ReportBody report={report} /> : <p className="text-sm text-muted">{empty}</p>}
    </section>
  );
}

export function YtOverview({ tenantId, canWork }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt");
  const { data, load } = useDashboard(tenantId);
  const [videos, setVideos] = useState<YtVideo[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/tenants/${tenantId}/youtube`;

  const loadVideos = useCallback(async () => {
    try {
      setVideos(await api<YtVideo[]>(`${base}/videos`));
    } catch {
      setVideos([]);
    }
  }, [base]);
  useEffect(() => {
    if (data?.connection && data.addon.active) loadVideos();
  }, [data?.connection, data?.addon.active, loadVideos]);
  const running = Object.values(data?.latest ?? {}).some((r) => r?.status === "running");
  usePoll(running, load);

  const subs = useCountUp(data?.channel?.subscribers ?? null);

  async function act(key: string, path: string) {
    setBusy(key);
    setError(null);
    try {
      await api(`${base}${path}`, { method: "POST" });
      await load();
      if (key === "sync") await loadVideos();
    } catch (err) {
      setError(errorText(err, t("error")));
    } finally {
      setBusy(null);
    }
  }

  return (
    <StudioGate tenantId={tenantId} data={data}>
      {data?.connection && (
        <div className="space-y-5">
          <section className="ch-card relative overflow-hidden rounded-2xl border border-border bg-surface p-5" style={{ ["--ch-glow" as string]: "#FF0000" }}>
            <div className="flex flex-wrap items-start gap-4">
              <LogoOrb channel="youtube" live={data.connection.status === "active"} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  {data.connection.avatar && <img src={data.connection.avatar} alt="" className="h-6 w-6 rounded-full" />}
                  <h1 className="truncate text-xl font-semibold">{data.connection.name}</h1>
                </div>
                <p className="text-sm text-muted">{data.connection.handle}</p>
                {data.connection.status !== "active" && <p className="mt-1 text-sm text-danger">{data.connection.last_error}</p>}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <CreditPill total={data.addon.total} />
                {canWork && (
                  <CostButton variant="ghost" busy={busy === "sync"} onClick={() => act("sync", "/sync")}>{t("sync")}</CostButton>
                )}
              </div>
            </div>
            <div className="mt-5 grid gap-5 md:grid-cols-[auto_1fr]">
              <div className="flex gap-8">
                <div>
                  <p className="text-4xl font-semibold tabular-nums leading-none">{formatCount(subs)}</p>
                  <p className="mt-1 text-xs text-muted">{t("subscribers")}</p>
                  {data.channel?.growth_7d !== null && data.channel?.growth_7d !== undefined && (
                    <p className={`mt-1 text-xs font-medium ${data.channel.growth_7d >= 0 ? "text-success" : "text-danger"}`}>
                      {data.channel.growth_7d >= 0 ? "▲ +" : "▼ "}{data.channel.growth_7d} · {t("week")}
                    </p>
                  )}
                </div>
                <div>
                  <p className="text-2xl font-semibold tabular-nums leading-none">{formatCount(data.channel?.views)}</p>
                  <p className="mt-1 text-xs text-muted">{t("totalViews")}</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold tabular-nums leading-none">{formatCount(data.channel?.videos)}</p>
                  <p className="mt-1 text-xs text-muted">{t("videos")}</p>
                </div>
              </div>
              <Sparkline points={(data.channel?.series ?? []).map((p) => ({ day: p.day, followers: p.subscribers }))} color="#FF3B3B" />
            </div>
          </section>

          {error && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}

          <div className="grid gap-4 lg:grid-cols-2">
            <ReportCard title={t("pulseTitle")} report={data.latest?.pulse} empty={t("pulseEmpty")} />
            <ReportCard title={t("dailyTitle")} report={data.latest?.daily} empty={t("dailyEmpty")} />
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t("reviewTitle")}</h3>
              <p className="flex-1 text-sm text-muted" dir="auto">
                {data.latest?.review?.status === "done" ? data.latest.review.output?.headline : t("reviewHint")}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {canWork && (
                  <CostButton cost={data.addon.costs.review} busy={busy === "review" || data.latest?.review?.status === "running"}
                    onClick={() => act("review", "/reports/review")}>{t("reviewRun")}</CostButton>
                )}
                {data.latest?.review && <Link href={`/t/${tenantId}/youtube/reports`} className="text-xs text-accent underline">{t("open")}</Link>}
              </div>
            </section>
            <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t("ideasTitle")}</h3>
              <p className="flex-1 text-sm text-muted">{data.counts?.ideas_new ? t("ideasNew", { n: data.counts.ideas_new }) : t("ideasHint")}</p>
              <div className="flex flex-wrap items-center gap-2">
                {canWork && (
                  <CostButton cost={data.addon.costs.ideas} busy={busy === "ideas" || data.latest?.ideas?.status === "running"}
                    onClick={() => act("ideas", "/ideas/run")}>{t("ideasRun")}</CostButton>
                )}
                <Link href={`/t/${tenantId}/youtube/ideas`} className="text-xs text-accent underline">{t("open")}</Link>
              </div>
            </section>
            <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t("commentsTitle")}</h3>
              <p className="flex-1 text-3xl font-semibold tabular-nums">{data.counts?.replies_waiting ?? 0}</p>
              <p className="text-xs text-muted">{t("commentsWaiting")}</p>
              <Link href={`/t/${tenantId}/youtube/comments`} className="text-xs text-accent underline">{t("open")}</Link>
            </section>
          </div>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">{t("latestVideos")}</h2>
              <Link href={`/t/${tenantId}/youtube/videos`} className="text-xs text-accent underline">{t("allVideos")}</Link>
            </div>
            {videos === null ? (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="wf-skeleton aspect-video rounded-lg" />)}</div>
            ) : videos.length === 0 ? (
              <p className="text-sm text-muted">{t("noVideos")}</p>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {videos.slice(0, 8).map((v) => <VideoCard key={v.video_id} v={v} tenantId={tenantId} />)}
              </div>
            )}
          </section>
        </div>
      )}
    </StudioGate>
  );
}
