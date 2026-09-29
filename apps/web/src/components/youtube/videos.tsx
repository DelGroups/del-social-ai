"use client";

// All videos of the channel, filterable, each opening its own studio (kit and thumbnails).
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import type { YtVideo } from "@/lib/youtube";

import { StudioGate, useDashboard } from "./common";
import { VideoCard } from "./overview";

export function YtVideos({ tenantId }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt");
  const { data } = useDashboard(tenantId);
  const [videos, setVideos] = useState<YtVideo[] | null>(null);
  const [filter, setFilter] = useState<"all" | "long" | "shorts" | "todo">("all");
  const [q, setQ] = useState("");
  const load = useCallback(async () => {
    try {
      setVideos(await api<YtVideo[]>(`/tenants/${tenantId}/youtube/videos`));
    } catch {
      setVideos([]);
    }
  }, [tenantId]);
  useEffect(() => {
    if (data?.connection && data.addon.active) load();
  }, [data?.connection, data?.addon.active, load]);

  const shown = (videos ?? []).filter((v) =>
    (filter === "all" || (filter === "long" && !v.is_short) || (filter === "shorts" && v.is_short) || (filter === "todo" && v.kit !== "applied"))
    && (!q.trim() || v.title.toLowerCase().includes(q.trim().toLowerCase())));

  return (
    <StudioGate tenantId={tenantId} data={data}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {(["all", "long", "shorts", "todo"] as const).map((f) => (
            <button key={f} type="button" onClick={() => setFilter(f)}
              className={`rounded-full border px-3 py-1 text-xs ${filter === f ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-text"}`}>
              {t(`filter.${f}`)}
            </button>
          ))}
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")}
            className="ml-auto w-full max-w-xs rounded-md border border-border bg-bg px-3 py-1.5 text-sm focus:border-accent focus:outline-none sm:w-auto" />
        </div>
        {videos === null ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[0, 1, 2, 3, 4, 5, 6, 7].map((i) => <div key={i} className="wf-skeleton aspect-video rounded-lg" />)}</div>
        ) : shown.length === 0 ? (
          <p className="text-sm text-muted">{t("noVideos")}</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{shown.map((v) => <VideoCard key={v.video_id} v={v} tenantId={tenantId} />)}</div>
        )}
      </div>
    </StudioGate>
  );
}
