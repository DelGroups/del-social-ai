"use client";

// One video's studio: its numbers, the publishing kit and the thumbnail designs.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { formatCount } from "@/components/channel-cards";
import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { YtDraft, YtThumb, YtVideo } from "@/lib/youtube";
import { duration } from "@/lib/youtube";

import { CreditPill, StudioGate, useDashboard, usePoll } from "./common";
import { KitPanel } from "./kit-panel";
import { ThumbStudio } from "./thumb-studio";

type Detail = { video: YtVideo; drafts: YtDraft[]; thumbnails: YtThumb[] };

export function VideoStudio({ tenantId, videoId, canWork, initialTab = "thumbs" }: {
  tenantId: string; videoId: string; canWork: boolean; initialTab?: "thumbs" | "kit";
}) {
  const t = useTranslations("yt");
  const { data, load: loadDash } = useDashboard(tenantId);
  const [d, setD] = useState<Detail | null>(null);
  const [tab, setTab] = useState<"thumbs" | "kit">(initialTab);
  const [missing, setMissing] = useState(false);
  const load = useCallback(async () => {
    try {
      setD(await api<Detail>(`/tenants/${tenantId}/youtube/videos/${videoId}`));
    } catch {
      setMissing(true);
    }
  }, [tenantId, videoId]);
  useEffect(() => {
    if (data?.connection && data.addon.active) load();
  }, [data?.connection, data?.addon.active, load]);
  const refresh = useCallback(() => {
    load();
    loadDash();
  }, [load, loadDash]);
  usePoll(!!d && (d.drafts.some((x) => x.status === "running") || d.thumbnails.some((x) => x.status === "working")), refresh);

  return (
    <StudioGate tenantId={tenantId} data={data}>
      {missing ? <p className="text-sm text-muted">{t("videoMissing")}</p> : !d ? <div className="wf-skeleton h-48 rounded-xl" /> : (
        <div className="space-y-5">
          <Link href={`/t/${tenantId}/youtube/videos`} className="text-xs text-muted hover:text-text">← {t("allVideos")}</Link>
          <section className="flex flex-wrap gap-4 rounded-xl border border-border bg-surface p-4">
            {d.video.thumbnail_url && <img src={d.video.thumbnail_url} alt="" className="aspect-video w-56 rounded-lg object-cover" />}
            <div className="min-w-0 flex-1 space-y-1">
              <h1 className="text-lg font-semibold leading-snug" dir="auto">{d.video.title}</h1>
              <p className="text-xs text-muted">
                {d.video.published_at ? formatDateTime(d.video.published_at) : ""} · {d.video.is_short ? "Shorts" : duration(d.video.duration_s)}
                {d.video.privacy ? ` · ${t(`privacy.${d.video.privacy}`)}` : ""}
              </p>
              <div className="flex flex-wrap gap-5 pt-2 text-sm">
                <span><b className="tabular-nums">{formatCount(d.video.views)}</b> <span className="text-muted">{t("views")}</span></span>
                <span><b className="tabular-nums">{formatCount(d.video.likes)}</b> <span className="text-muted">{t("likes")}</span></span>
                <span><b className="tabular-nums">{formatCount(d.video.comments)}</b> <span className="text-muted">{t("commentsWord")}</span></span>
              </div>
              <div className="flex flex-wrap gap-3 pt-2 text-xs">
                <a href={`https://youtu.be/${d.video.video_id}`} target="_blank" rel="noreferrer" className="text-accent underline">{t("openYoutube")}</a>
                <a href={`https://studio.youtube.com/video/${d.video.video_id}/edit`} target="_blank" rel="noreferrer" className="text-accent underline">YouTube Studio</a>
              </div>
            </div>
            {data && <div><CreditPill total={data.addon.total} /></div>}
          </section>
          <div className="flex gap-1 border-b border-border">
            {(["thumbs", "kit"] as const).map((k) => (
              <button key={k} type="button" onClick={() => setTab(k)}
                className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? "border-[#FF0000] font-medium" : "border-transparent text-muted"}`}>
                {t(`videoTab.${k}`)}
              </button>
            ))}
          </div>
          {tab === "thumbs" ? (
            <ThumbStudio tenantId={tenantId} video={d.video} thumbs={d.thumbnails} canWork={canWork} costs={data?.addon.costs ?? {}}
              channelName={data?.connection?.name ?? ""} onChange={refresh} />
          ) : (
            <KitPanel tenantId={tenantId} video={d.video} drafts={d.drafts} canWork={canWork} onChange={refresh} costs={data?.addon.costs ?? {}} />
          )}
        </div>
      )}
    </StudioGate>
  );
}
