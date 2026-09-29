"use client";

// Video lab: upload a video (in chunks, with progress), then transcribe, cut silences, add
// subtitles, cut Shorts, export, send to YouTube — or make a video with AI from an idea.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import { duration } from "@/lib/youtube";

import { CostButton, CreditPill, StudioGate, errorText, useDashboard, usePoll } from "./common";

type Media = {
  media_id: string; kind: "upload" | "render" | "generated"; status: "uploading" | "ready" | "failed"; title: string; bytes: number;
  expected_bytes: number | null; duration_s: number | null; width: number | null; height: number | null; has_transcript: boolean;
  youtube_video_id: string | null; error: string | null; video: string | null; created_at: string; expires_at: string;
};
type Job = { job_id: string; media_id: string | null; kind: string; status: "queued" | "running" | "done" | "failed"; progress: number;
  result: Record<string, any> | null; credits: number; error: string | null; created_at: string };
type VModel = { key: string; name: string; tier: string; durations: number[]; aspects: string[]; credits_per_second: number; audio: boolean; image: boolean };
type LabData = { media: Media[]; jobs: Job[]; models: VModel[]; usage_bytes: number; limits: { upload_bytes: number; space_bytes: number; chunk_bytes: number } };

const gb = (n: number) => `${(n / 1024 ** 3).toFixed(n > 10 * 1024 ** 3 ? 0 : 1)} GB`;
const STYLES = ["cinematic", "realistic", "documentary", "anime", "3d", "product", "retro", "drone"] as const;
const field = "w-full rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none";

function Uploader({ base, chunk, onDone }: { base: string; chunk: number; onDone: () => void }) {
  const t = useTranslations("yt.lab");
  const input = useRef<HTMLInputElement>(null);
  const [pct, setPct] = useState<number | null>(null);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(file: File) {
    setError(null);
    setPct(0);
    try {
      const { media_id } = await api<{ media_id: string }>(`${base}/uploads`, { method: "POST", body: { filename: file.name, size: file.size } });
      for (let offset = 0; offset < file.size; offset += chunk) {
        const part = file.slice(offset, offset + chunk);
        let tries = 0;
        for (;;) {
          const res = await fetch(`/api${base}/uploads/${media_id}?offset=${offset}`, { method: "PUT", body: part, credentials: "same-origin" });
          if (res.ok) break;
          if (++tries > 3) throw new Error((await res.json().catch(() => null))?.detail ?? t("uploadFailed"));
          await new Promise((r) => setTimeout(r, 1500 * tries));
        }
        setPct(Math.round(((offset + part.size) / file.size) * 100));
      }
      const done = await api<Media>(`${base}/uploads/${media_id}/complete`, { method: "POST" });
      if (done.status === "failed") setError(done.error);
      onDone();
    } catch (err) {
      setError(errorText(err, err instanceof Error ? err.message : t("uploadFailed")));
    } finally {
      setPct(null);
    }
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) send(f); }}
      className={`ch-card relative flex flex-col items-center gap-3 overflow-hidden rounded-2xl border-2 border-dashed p-8 text-center transition ${drag ? "border-[#FF0000] bg-[#FF0000]/5" : "border-border bg-surface"}`}
      style={{ ["--ch-glow" as string]: "#FF0000" }}
    >
      <svg viewBox="0 0 24 24" className="h-10 w-10 text-[#FF4D4D]" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></svg>
      <p className="font-semibold">{t("dropTitle")}</p>
      <p className="text-xs text-muted">{t("dropHint")}</p>
      {pct === null ? (
        <button type="button" onClick={() => input.current?.click()} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text">{t("choose")}</button>
      ) : (
        <div className="w-full max-w-md space-y-1">
          <div className="h-2 overflow-hidden rounded-full bg-bg"><div className="h-full rounded-full bg-[#FF0000] transition-all" style={{ width: `${pct}%` }} /></div>
          <p className="text-xs tabular-nums text-muted">{t("uploading", { pct })}</p>
        </div>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
      <input ref={input} type="file" accept="video/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = ""; }} />
    </div>
  );
}

type Tool = "transcribe" | "cut" | "subtitles" | "shorts" | "export" | "upload";

function Tools({ base, m, costs, onStarted }: { base: string; m: Media; costs: Record<string, number>; onStarted: () => void }) {
  const t = useTranslations("yt.lab");
  const [tool, setTool] = useState<Tool | null>(null);
  const [o, setO] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mins = Math.max(1, Math.ceil((m.duration_s ?? 0) / 60));
  const cost: Record<Tool, number> = {
    transcribe: Math.max(1, Math.ceil((m.duration_s ?? 0) / 600)) * (costs.transcribe_10min ?? 1),
    cut: mins * (costs.render_min ?? 1),
    subtitles: mins * (costs.render_min ?? 1) + (o.translate_to ? costs.metadata ?? 1 : 0),
    shorts: (costs.shorts_pick ?? 1) + (o.count ?? 3) * (costs.render_min ?? 1),
    export: mins * (costs.render_min ?? 1),
    upload: 0,
  };
  async function go() {
    if (!tool) return;
    setBusy(true);
    setError(null);
    let body: Record<string, any> = {};
    if (tool === "transcribe") body = o.language ? { language: o.language } : {};
    if (tool === "cut") body = { level: o.level ?? "normal", loudness: true };
    if (tool === "subtitles") body = { translate_to: o.translate_to || null, style: { font: o.font ?? "bold", box: !!o.box, position: o.position ?? "bottom", size: o.size ?? "m", uppercase: !!o.uppercase } };
    if (tool === "shorts") body = { count: o.count ?? 3, frame: o.frame ?? "vertical_blur", hook: o.hook ?? true };
    if (tool === "export") body = { start: Number(o.start ?? 0), end: o.end ? Number(o.end) : null, speed: Number(o.speed ?? 1), frame: o.frame ?? "original", loudness: true, subtitles: !!o.subs && m.has_transcript };
    if (tool === "upload") body = { title: o.title || m.title, description: o.description ?? "", privacy: o.privacy ?? "private", publish_at: o.at ? new Date(o.at).toISOString() : null };
    try {
      await api(`${base}/media/${m.media_id}/${tool}`, { method: "POST", body });
      setTool(null);
      onStarted();
    } catch (err) {
      setError(errorText(err, t("error")));
    } finally {
      setBusy(false);
    }
  }
  const needs = (x: Tool) => (x === "subtitles" || x === "shorts") && !m.has_transcript;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {(["transcribe", "cut", "subtitles", "shorts", "export", "upload"] as const).map((x) => (
          <button key={x} type="button" disabled={needs(x)} title={needs(x) ? t("needTranscript") : undefined} onClick={() => { setTool(tool === x ? null : x); setO({}); }}
            className={`rounded-full border px-3 py-1 text-xs disabled:opacity-40 ${tool === x ? "border-[#FF0000] bg-[#FF0000]/10 text-text" : "border-border text-muted hover:text-text"}`}>
            {t(`tool.${x}`)}
          </button>
        ))}
      </div>
      {tool && (
        <div className="space-y-3 rounded-lg bg-bg p-3 text-sm">
          <p className="text-xs text-muted">{t(`toolHint.${tool}`)}</p>
          {tool === "transcribe" && (
            <select className={field} value={o.language ?? ""} onChange={(e) => setO({ ...o, language: e.target.value })}>
              <option value="">{t("autoLanguage")}</option>
              {["az", "ru", "en", "tr"].map((l) => <option key={l} value={l}>{t(`lang.${l}`)}</option>)}
            </select>
          )}
          {tool === "cut" && (
            <div className="flex flex-wrap gap-1.5">
              {["gentle", "normal", "tight"].map((l) => (
                <button key={l} type="button" onClick={() => setO({ ...o, level: l })} className={`rounded-md border px-3 py-1 text-xs ${(o.level ?? "normal") === l ? "border-accent text-accent" : "border-border"}`}>{t(`level.${l}`)}</button>
              ))}
            </div>
          )}
          {tool === "subtitles" && (
            <div className="grid gap-2 sm:grid-cols-2">
              <select className={field} value={o.translate_to ?? ""} onChange={(e) => setO({ ...o, translate_to: e.target.value })}>
                <option value="">{t("noTranslate")}</option>
                {["az", "ru", "en", "tr"].map((l) => <option key={l} value={l}>{t("translateTo", { lang: t(`lang.${l}`) })}</option>)}
              </select>
              <select className={field} value={o.font ?? "bold"} onChange={(e) => setO({ ...o, font: e.target.value })}>
                {["bold", "condensed", "wide", "tech", "elegant", "rounded"].map((f) => <option key={f} value={f}>{t(`font.${f}`)}</option>)}
              </select>
              <select className={field} value={o.position ?? "bottom"} onChange={(e) => setO({ ...o, position: e.target.value })}>
                {["bottom", "middle", "top"].map((p) => <option key={p} value={p}>{t(`pos.${p}`)}</option>)}
              </select>
              <select className={field} value={o.size ?? "m"} onChange={(e) => setO({ ...o, size: e.target.value })}>
                {["s", "m", "l"].map((z) => <option key={z} value={z}>{t(`size.${z}`)}</option>)}
              </select>
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={!!o.box} onChange={(e) => setO({ ...o, box: e.target.checked })} />{t("box")}</label>
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={!!o.uppercase} onChange={(e) => setO({ ...o, uppercase: e.target.checked })} />{t("caps")}</label>
            </div>
          )}
          {tool === "shorts" && (
            <div className="grid gap-2 sm:grid-cols-2">
              <select className={field} value={o.count ?? 3} onChange={(e) => setO({ ...o, count: Number(e.target.value) })}>
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{t("shortsCount", { n })}</option>)}
              </select>
              <select className={field} value={o.frame ?? "vertical_blur"} onChange={(e) => setO({ ...o, frame: e.target.value })}>
                <option value="vertical_blur">{t("frame.vertical_blur")}</option>
                <option value="vertical_center">{t("frame.vertical_center")}</option>
              </select>
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={o.hook ?? true} onChange={(e) => setO({ ...o, hook: e.target.checked })} />{t("hookText")}</label>
            </div>
          )}
          {tool === "export" && (
            <div className="grid gap-2 sm:grid-cols-3">
              <input className={field} type="number" min={0} step={0.1} placeholder={t("start")} value={o.start ?? ""} onChange={(e) => setO({ ...o, start: e.target.value })} />
              <input className={field} type="number" min={0} step={0.1} placeholder={t("end", { max: Math.round(m.duration_s ?? 0) })} value={o.end ?? ""} onChange={(e) => setO({ ...o, end: e.target.value })} />
              <select className={field} value={o.speed ?? 1} onChange={(e) => setO({ ...o, speed: e.target.value })}>
                {[0.75, 1, 1.25, 1.5, 2].map((s) => <option key={s} value={s}>{s}×</option>)}
              </select>
              <select className={`${field} sm:col-span-2`} value={o.frame ?? "original"} onChange={(e) => setO({ ...o, frame: e.target.value })}>
                {["original", "landscape", "vertical_blur", "vertical_center", "square"].map((f) => <option key={f} value={f}>{t(`frame.${f}`)}</option>)}
              </select>
              {m.has_transcript && <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={!!o.subs} onChange={(e) => setO({ ...o, subs: e.target.checked })} />{t("withSubs")}</label>}
            </div>
          )}
          {tool === "upload" && (
            <div className="grid gap-2">
              <input className={field} maxLength={100} placeholder={t("ytTitle")} value={o.title ?? m.title} onChange={(e) => setO({ ...o, title: e.target.value })} dir="auto" />
              <textarea className={field} rows={3} placeholder={t("ytDescription")} value={o.description ?? ""} onChange={(e) => setO({ ...o, description: e.target.value })} dir="auto" />
              <div className="grid gap-2 sm:grid-cols-2">
                <select className={field} value={o.privacy ?? "private"} onChange={(e) => setO({ ...o, privacy: e.target.value })}>
                  {["private", "unlisted", "public"].map((p) => <option key={p} value={p}>{t(`privacy.${p}`)}</option>)}
                </select>
                <input className={field} type="datetime-local" value={o.at ?? ""} onChange={(e) => setO({ ...o, at: e.target.value })} title={t("scheduleHint")} />
              </div>
              {m.kind === "generated" && <p className="text-xs text-muted">{t("aiDisclosure")}</p>}
            </div>
          )}
          <CostButton cost={cost[tool] || undefined} busy={busy} onClick={go}>{t(`run.${tool}`)}</CostButton>
          {error && <p className="text-sm text-danger">{error}</p>}
        </div>
      )}
    </div>
  );
}

function Generator({ base, models, onStarted }: { base: string; models: VModel[]; onStarted: () => void }) {
  const t = useTranslations("yt.lab");
  const [idea, setIdea] = useState("");
  const [style, setStyle] = useState<(typeof STYLES)[number]>("cinematic");
  const [modelKey, setModelKey] = useState(models[1]?.key ?? models[0]?.key);
  const model = models.find((x) => x.key === modelKey) ?? models[0];
  const [seconds, setSeconds] = useState(model?.durations[0] ?? 5);
  const [aspect, setAspect] = useState("16:9");
  const [scenes, setScenes] = useState(1);
  const [captions, setCaptions] = useState(false);
  const [image, setImage] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (model && !model.durations.includes(seconds)) setSeconds(model.durations[0]);
    if (model && !model.aspects.includes(aspect)) setAspect(model.aspects[0]);
  }, [model, seconds, aspect]);
  if (!model) return null;
  const credits = model.credits_per_second * seconds * scenes;

  async function go() {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("options", JSON.stringify({ idea, style, model: model.key, seconds, aspect, scenes, captions }));
    if (image) form.append("image", image);
    try {
      const res = await fetch(`/api${base}/generate`, { method: "POST", body: form, credentials: "same-origin" });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? t("error"));
      setIdea("");
      onStarted();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4 rounded-2xl border border-border bg-surface p-5">
      <div>
        <h2 className="text-base font-semibold">{t("genTitle")}</h2>
        <p className="text-xs text-muted">{t("genHint")}</p>
      </div>
      <textarea rows={3} value={idea} onChange={(e) => setIdea(e.target.value)} placeholder={t("idea")} className={field} dir="auto" />
      <div className="space-y-1.5">
        <p className="text-xs font-semibold text-muted">{t("style")}</p>
        <div className="flex flex-wrap gap-1.5">
          {STYLES.map((s) => (
            <button key={s} type="button" onClick={() => setStyle(s)} className={`rounded-full border px-3 py-1 text-xs ${style === s ? "border-[#FF0000] bg-[#FF0000]/10" : "border-border text-muted"}`}>{t(`styles.${s}`)}</button>
          ))}
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {models.map((x) => (
          <button key={x.key} type="button" onClick={() => setModelKey(x.key)}
            className={`rounded-lg border p-3 text-left text-sm ${x.key === model.key ? "border-[#FF0000] bg-[#FF0000]/5" : "border-border"}`}>
            <b className="block">{x.name}</b>
            <span className="text-xs text-muted">{t("perSecond", { n: x.credits_per_second })}{x.audio ? ` · ${t("withSound")}` : ""}</span>
          </button>
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-4">
        <select className={field} value={seconds} onChange={(e) => setSeconds(Number(e.target.value))}>{model.durations.map((d) => <option key={d} value={d}>{t("seconds", { n: d })}</option>)}</select>
        <select className={field} value={aspect} onChange={(e) => setAspect(e.target.value)}>{model.aspects.map((a) => <option key={a} value={a}>{a}</option>)}</select>
        <select className={field} value={scenes} onChange={(e) => setScenes(Number(e.target.value))}>{[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{t("scenes", { n })}</option>)}</select>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={captions} onChange={(e) => setCaptions(e.target.checked)} />{t("captions")}</label>
      </div>
      {model.image && (
        <label className="flex flex-wrap items-center gap-2 text-xs text-muted">
          {t("startImage")} <input type="file" accept="image/*" onChange={(e) => setImage(e.target.files?.[0] ?? null)} />
        </label>
      )}
      <CostButton cost={credits} busy={busy} disabled={idea.trim().length < 3} onClick={go}>{t("generate")}</CostButton>
      {error && <p className="text-sm text-danger">{error}</p>}
    </section>
  );
}

export function YtLab({ tenantId, canWork }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt.lab");
  const { data: dash, load: loadDash } = useDashboard(tenantId);
  const [lab, setLab] = useState<LabData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const base = `/tenants/${tenantId}/youtube/lab`;
  const load = useCallback(async () => {
    try {
      setLab(await api<LabData>(base));
    } catch {
      /* keep */
    }
  }, [base]);
  useEffect(() => {
    if (dash?.addon.active) load();
  }, [dash?.addon.active, load]);
  const refresh = useCallback(() => {
    load();
    loadDash();
  }, [load, loadDash]);
  usePoll(!!lab?.jobs.some((j) => j.status === "queued" || j.status === "running"), refresh);

  const jobsFor = (id: string) => (lab?.jobs ?? []).filter((j) => j.media_id === id).slice(0, 3);
  return (
    <StudioGate tenantId={tenantId} data={dash} requireChannel={false}>
      {lab && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <span>{t("space", { used: gb(lab.usage_bytes), total: gb(lab.limits.space_bytes) })} · {t("kept")}</span>
            {dash && <CreditPill total={dash.addon.total} />}
          </div>
          {canWork && <Uploader base={base} chunk={lab.limits.chunk_bytes} onDone={refresh} />}

          {lab.jobs.some((j) => j.status === "queued" || j.status === "running") && (
            <section className="space-y-2 rounded-xl border border-border bg-surface p-4">
              {lab.jobs.filter((j) => j.status === "queued" || j.status === "running").map((j) => (
                <div key={j.job_id} className="space-y-1 text-sm">
                  <div className="flex justify-between"><span>{t(`tool.${j.kind}`)}</span><span className="tabular-nums text-muted">{j.status === "queued" ? t("queued") : `${j.progress}%`}</span></div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-bg"><div className="h-full rounded-full bg-[#FF0000] transition-all" style={{ width: `${Math.max(3, j.progress)}%` }} /></div>
                </div>
              ))}
            </section>
          )}

          <section className="space-y-3">
            <h2 className="text-sm font-semibold">{t("library")}</h2>
            {lab.media.length === 0 ? <p className="text-sm text-muted">{t("empty")}</p> : (
              <div className="grid gap-4 lg:grid-cols-2">
                {lab.media.map((m) => (
                  <article key={m.media_id} className="space-y-3 rounded-xl border border-border bg-surface p-3">
                    {m.video ? (
                      <video src={`/api${m.video}`} controls preload="metadata" className={`w-full rounded-lg bg-black ${m.height && m.width && m.height > m.width ? "mx-auto max-h-96 w-auto" : ""}`} />
                    ) : (
                      <div className="grid aspect-video place-items-center rounded-lg bg-bg text-sm text-muted">
                        {m.status === "uploading" ? t("stillUploading") : m.error}
                      </div>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="min-w-0 flex-1 truncate text-sm font-medium" dir="auto">{m.title}</p>
                      <span className="rounded-full bg-bg px-2 py-0.5 text-[11px] text-muted">{t(`kind.${m.kind}`)}</span>
                      {m.has_transcript && <span className="rounded-full bg-success/15 px-2 py-0.5 text-[11px] text-success">{t("hasText")}</span>}
                    </div>
                    <p className="text-xs text-muted">
                      {duration(Math.round(m.duration_s ?? 0))}{m.width ? ` · ${m.width}×${m.height}` : ""} · {formatDateTime(m.created_at)}
                      {m.youtube_video_id && <> · <a href={`https://youtu.be/${m.youtube_video_id}`} target="_blank" rel="noreferrer" className="text-accent underline">YouTube</a></>}
                    </p>
                    {jobsFor(m.media_id).filter((j) => j.status === "failed" || j.status === "done").slice(0, 1).map((j) => (
                      <p key={j.job_id} className={`text-xs ${j.status === "failed" ? "text-danger" : "text-success"}`}>
                        {t(`tool.${j.kind}`)}: {j.status === "failed" ? j.error : t("doneShort")}
                      </p>
                    ))}
                    {canWork && m.status === "ready" && (
                      open === m.media_id ? (
                        <Tools base={base} m={m} costs={dash?.addon.costs ?? {}} onStarted={refresh} />
                      ) : (
                        <div className="flex gap-3 text-xs">
                          <button type="button" onClick={() => setOpen(m.media_id)} className="font-medium text-accent underline">{t("work")}</button>
                          <a href={`/api${m.video}`} download className="text-muted underline">{t("download")}</a>
                          <button type="button" onClick={async () => { if (confirm(t("deleteConfirm"))) { await api(`${base}/media/${m.media_id}`, { method: "DELETE" }); load(); } }} className="text-muted underline">{t("delete")}</button>
                        </div>
                      )
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          {canWork && <Generator base={base} models={lab.models} onStarted={refresh} />}
        </div>
      )}
    </StudioGate>
  );
}
