"use client";

// Thumbnail studio for one video: AI concepts or a blank design, then every choice a creator
// needs — text, layout, colours, font, effects, background (frame, upload, AI, AI edit) and a
// cut-out subject — rendered by the API with real fonts, previewed as YouTube shows it, applied in one click.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/client-api";
import { FONTS, LAYOUTS, PALETTES, type ThumbSpec, type YtThumb, type YtVideo } from "@/lib/youtube";

import { CostButton, errorText } from "./common";

const img = (t: YtThumb) => `/api${t.image}`;

function LayoutIcon({ layout }: { layout: string }) {
  const bar = "fill-current opacity-80";
  const box: Record<string, React.ReactNode> = {
    left_text: <><rect x="4" y="8" width="16" height="4" className={bar} /><rect x="4" y="14" width="12" height="4" className={bar} /><circle cx="30" cy="16" r="6" className="fill-current opacity-40" /></>,
    right_text: <><rect x="20" y="8" width="16" height="4" className={bar} /><rect x="24" y="14" width="12" height="4" className={bar} /><circle cx="10" cy="16" r="6" className="fill-current opacity-40" /></>,
    center_big: <><rect x="6" y="9" width="28" height="5" className={bar} /><rect x="10" y="16" width="20" height="5" className={bar} /></>,
    top_banner: <><rect x="0" y="2" width="40" height="8" className="fill-current opacity-40" /><rect x="8" y="4" width="24" height="4" className={bar} /></>,
    bottom_bar: <><rect x="0" y="20" width="40" height="8" className="fill-current opacity-40" /><rect x="8" y="22" width="24" height="4" className={bar} /></>,
    split: <><rect x="8" y="4" width="24" height="5" className={bar} /><rect x="19" y="12" width="2" height="16" className="fill-current opacity-40" /></>,
    corner_badge: <><rect x="4" y="4" width="18" height="5" className={bar} /><rect x="4" y="11" width="12" height="4" className={bar} /></>,
    minimal: <rect x="4" y="21" width="18" height="3" className={bar} />,
  };
  return <svg viewBox="0 0 40 30" className="h-8 w-11">{box[layout]}</svg>;
}

/** The thumbnail as YouTube shows it: home feed card (desktop) and a phone row, dark mode. */
function YoutubePreview({ src, title, channel, views }: { src: string; title: string; channel: string; views: string }) {
  return (
    <div className="space-y-3 rounded-xl bg-[#0f0f0f] p-4 text-white">
      <div className="grid gap-4 sm:grid-cols-[1fr_260px]">
        <div className="space-y-2">
          <div className="relative overflow-hidden rounded-xl"><img src={src} alt="" className="w-full" /><span className="absolute bottom-1.5 right-1.5 rounded bg-black/80 px-1 text-[11px]">12:34</span></div>
          <div className="flex gap-3">
            <span className="mt-0.5 h-9 w-9 shrink-0 rounded-full bg-[#333]" />
            <div className="min-w-0">
              <p className="line-clamp-2 text-sm font-semibold leading-snug" dir="auto">{title}</p>
              <p className="mt-1 text-xs text-[#aaa]">{channel}</p>
              <p className="text-xs text-[#aaa]">{views}</p>
            </div>
          </div>
        </div>
        <div className="space-y-2">
          <p className="text-[11px] uppercase tracking-wide text-[#aaa]">Mobile · Up next</p>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex gap-2">
              <div className={`w-[168px] shrink-0 overflow-hidden rounded-lg ${i ? "bg-[#272727]" : ""}`} style={{ aspectRatio: "16 / 9" }}>
                {i === 0 && <img src={src} alt="" className="h-full w-full object-cover" />}
              </div>
              <div className="min-w-0 space-y-1 pt-0.5">
                {i === 0 ? <p className="line-clamp-2 text-xs font-semibold" dir="auto">{title}</p> : <><div className="h-2.5 w-20 rounded bg-[#272727]" /><div className="h-2.5 w-14 rounded bg-[#272727]" /></>}
                {i === 0 && <p className="text-[11px] text-[#aaa]">{channel}</p>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Toggle({ on, label, onChange }: { on: boolean; label: string; onChange: (v: boolean) => void }) {
  return (
    <button type="button" onClick={() => onChange(!on)} className={`rounded-full border px-2.5 py-1 text-xs ${on ? "border-accent bg-accent/10 text-accent" : "border-border text-muted"}`}>
      {on ? "✓ " : ""}{label}
    </button>
  );
}

function Slider({ label, value, min, max, step = 1, onChange }: { label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void }) {
  return (
    <label className="block space-y-1 text-xs">
      <span className="flex justify-between text-muted"><span>{label}</span><span className="tabular-nums">{value}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-[var(--accent)]" />
    </label>
  );
}

function Editor({ tenantId, thumb, video, channelName, costs, canWork, onSaved }: {
  tenantId: string; thumb: YtThumb; video: YtVideo; channelName: string; costs: Record<string, number>; canWork: boolean; onSaved: () => void;
}) {
  const t = useTranslations("yt");
  const [spec, setSpec] = useState<ThumbSpec>(thumb.spec);
  const [src, setSrc] = useState(img(thumb));
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const [upLayer, setUpLayer] = useState<"background" | "subject">("background");
  const base = `/tenants/${tenantId}/youtube/thumbnails/${thumb.thumbnail_id}`;

  useEffect(() => {
    setSpec(thumb.spec);
    setSrc(img(thumb));
  }, [thumb.thumbnail_id, thumb.rev]); // new design or a job finished: take the server's version

  // Re-render on the server shortly after the last change (the real fonts and layers live there)
  function change(next: Partial<ThumbSpec>) {
    const s = { ...spec, ...next };
    setSpec(s);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      try {
        const r = await api<YtThumb>(base, { method: "PUT", body: s });
        setSrc(img(r));
      } catch (err) {
        setMsg({ tone: "err", text: errorText(err, t("error")) });
      }
    }, 450);
  }
  async function run(key: string, fn: () => Promise<unknown>, ok?: string) {
    setBusy(key);
    setMsg(null);
    try {
      await fn();
      if (ok) setMsg({ tone: "ok", text: ok });
      onSaved();
    } catch (err) {
      setMsg({ tone: "err", text: errorText(err, t("error")) });
    } finally {
      setBusy(null);
    }
  }
  async function upload(f: File) {
    const body = new FormData();
    body.append("file", f);
    await run("upload", async () => {
      const res = await fetch(`/api${base}/upload?layer=${upLayer}`, { method: "POST", body, credentials: "same-origin" });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? t("error"));
    });
  }

  const working = thumb.status === "working" || busy !== null;
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
      <div className="space-y-4">
        <div className="relative overflow-hidden rounded-xl border border-border">
          <img src={src} alt="" className="w-full" />
          {thumb.status === "working" && (
            <div className="absolute inset-0 grid place-items-center bg-black/50">
              <span className="h-10 w-10 animate-spin rounded-full border-4 border-white border-t-transparent" />
            </div>
          )}
        </div>
        {thumb.error && <p className="text-sm text-danger">{thumb.error}</p>}
        {msg && <p className={`text-sm ${msg.tone === "ok" ? "text-success" : "text-danger"}`}>{msg.text}</p>}
        {canWork && (
          <div className="flex flex-wrap gap-2">
            <CostButton busy={busy === "apply"} disabled={working} onClick={() => confirm(t("thumbConfirm")) &&
              run("apply", () => api(`${base}/apply`, { method: "POST", body: { video_id: video.video_id } }), t("thumbApplied"))}>
              {t("thumbApply")}
            </CostButton>
            <a href={src} download={`thumbnail-${video.video_id}.jpg`} className="rounded-md border border-border px-3.5 py-2 text-sm hover:border-accent">{t("download")}</a>
          </div>
        )}
        <YoutubePreview src={src} title={video.title} channel={channelName} views={`${video.views ?? 0} views`} />
      </div>

      {canWork && (
        <aside className="space-y-4 rounded-xl border border-border bg-surface p-4">
          <div className="space-y-2">
            <input value={spec.text} maxLength={60} onChange={(e) => change({ text: e.target.value })} placeholder={t("thumbText")}
              className="w-full rounded-md border border-border bg-bg px-3 py-2 text-base font-semibold focus:border-accent focus:outline-none" dir="auto" />
            <div className="grid grid-cols-2 gap-2">
              <input value={spec.emphasis} maxLength={30} onChange={(e) => change({ emphasis: e.target.value })} placeholder={t("thumbEmphasis")}
                className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm focus:border-accent focus:outline-none" dir="auto" />
              <input value={spec.badge} maxLength={16} onChange={(e) => change({ badge: e.target.value })} placeholder={t("thumbBadge")}
                className="rounded-md border border-border bg-bg px-3 py-1.5 text-sm focus:border-accent focus:outline-none" dir="auto" />
            </div>
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-semibold text-muted">{t("thumbLayout")}</p>
            <div className="grid grid-cols-4 gap-1.5">
              {LAYOUTS.map((l) => (
                <button key={l} type="button" onClick={() => change({ layout: l })} title={t(`layout.${l}`)}
                  className={`grid place-items-center rounded-md border py-1 ${spec.layout === l ? "border-accent text-accent" : "border-border text-muted hover:text-text"}`}>
                  <LayoutIcon layout={l} />
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-semibold text-muted">{t("thumbColours")}</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(PALETTES).map(([name, [text, emph, band]]) => (
                <button key={name} type="button" onClick={() => change({ palette: name })} title={name}
                  className={`flex h-8 w-12 overflow-hidden rounded-md border-2 ${spec.palette === name ? "border-accent" : "border-transparent"}`}>
                  <span className="flex-1" style={{ background: band }} /><span className="flex-1" style={{ background: emph }} /><span className="flex-1" style={{ background: text }} />
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-semibold text-muted">{t("thumbFont")}</p>
            <div className="flex flex-wrap gap-1.5">
              {FONTS.map((f) => (
                <button key={f} type="button" onClick={() => change({ font: f })}
                  className={`rounded-md border px-2.5 py-1 text-xs ${spec.font === f ? "border-accent text-accent" : "border-border text-muted"}`}>{t(`font.${f}`)}</button>
              ))}
              {(["m", "l", "xl"] as const).map((z) => (
                <button key={z} type="button" onClick={() => change({ size: z })}
                  className={`rounded-md border px-2.5 py-1 text-xs uppercase ${spec.size === z ? "border-accent text-accent" : "border-border text-muted"}`}>{z}</button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Toggle on={spec.uppercase} label={t("fx.upper")} onChange={(v) => change({ uppercase: v })} />
            <Toggle on={spec.outline} label={t("fx.outline")} onChange={(v) => change({ outline: v })} />
            <Toggle on={spec.shadow} label={t("fx.shadow")} onChange={(v) => change({ shadow: v })} />
            <Toggle on={spec.glow} label={t("fx.glow")} onChange={(v) => change({ glow: v })} />
            <Toggle on={spec.frame} label={t("fx.frame")} onChange={(v) => change({ frame: v })} />
            <Toggle on={spec.arrow !== "none"} label={t("fx.arrow")} onChange={(v) => change({ arrow: v ? (spec.subject === "left" ? "left" : "right") : "none" })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Slider label={t("fx.darken")} value={spec.darken} min={0} max={85} onChange={(v) => change({ darken: v })} />
            <Slider label={t("fx.blur")} value={spec.blur} min={0} max={20} onChange={(v) => change({ blur: v })} />
            <Slider label={t("fx.saturation")} value={spec.saturation} min={0.5} max={1.8} step={0.05} onChange={(v) => change({ saturation: v })} />
            <Slider label={t("fx.brightness")} value={spec.brightness} min={0.6} max={1.5} step={0.05} onChange={(v) => change({ brightness: v })} />
          </div>

          <div className="space-y-2 border-t border-border pt-3">
            <p className="text-xs font-semibold text-muted">{t("thumbBackground")}</p>
            <div className="flex flex-wrap gap-1.5">
              <CostButton variant="ghost" disabled={working || !video.video_id} onClick={() => run("frame", () => api(`${base}/background`, { method: "POST", body: { mode: "youtube" } }))}>{t("bg.frame")}</CostButton>
              <CostButton variant="ghost" disabled={working} onClick={() => { setUpLayer("background"); file.current?.click(); }}>{t("bg.upload")}</CostButton>
              <CostButton variant="ghost" disabled={working} onClick={() => run("palette", () => api(`${base}/background`, { method: "POST", body: { mode: "palette" } }))}>{t("bg.colours")}</CostButton>
            </div>
            <textarea rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t("bg.prompt")}
              className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none" dir="auto" />
            <div className="flex flex-wrap gap-1.5">
              <CostButton cost={costs.thumbnail_ai} disabled={working || !prompt.trim()} busy={busy === "ai"}
                onClick={() => run("ai", () => api(`${base}/background`, { method: "POST", body: { mode: "ai", prompt } }))}>{t("bg.ai")}</CostButton>
              <CostButton variant="ghost" cost={costs.thumbnail_edit} disabled={working || !prompt.trim()} busy={busy === "edit"}
                onClick={() => run("edit", () => api(`${base}/background`, { method: "POST", body: { mode: "edit", prompt } }))}>{t("bg.edit")}</CostButton>
            </div>
          </div>
          <div className="space-y-2 border-t border-border pt-3">
            <p className="text-xs font-semibold text-muted">{t("thumbSubject")}</p>
            <div className="flex flex-wrap gap-1.5">
              <CostButton variant="ghost" cost={costs.cutout} disabled={working} busy={busy === "cut"}
                onClick={() => run("cut", () => api(`${base}/cutout`, { method: "POST" }))}>{t("subject.cut")}</CostButton>
              <CostButton variant="ghost" cost={costs.cutout} disabled={working} onClick={() => { setUpLayer("subject"); file.current?.click(); }}>{t("subject.upload")}</CostButton>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {(["none", "left", "center", "right"] as const).map((p) => (
                <button key={p} type="button" onClick={() => change({ subject: p })}
                  className={`rounded-md border px-2.5 py-1 text-xs ${spec.subject === p ? "border-accent text-accent" : "border-border text-muted"}`}>{t(`subject.${p}`)}</button>
              ))}
            </div>
            {spec.subject !== "none" && (
              <>
                <Slider label={t("subject.scale")} value={spec.subject_scale} min={0.5} max={1.2} step={0.05} onChange={(v) => change({ subject_scale: v })} />
                <Toggle on={spec.subject_outline} label={t("subject.outline")} onChange={(v) => change({ subject_outline: v })} />
              </>
            )}
          </div>
          <input ref={file} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
        </aside>
      )}
    </div>
  );
}

export function ThumbStudio({ tenantId, video, thumbs, canWork, costs, channelName, onChange }: {
  tenantId: string; video: YtVideo; thumbs: YtThumb[]; canWork: boolean; costs: Record<string, number>; channelName: string; onChange: () => void;
}) {
  const t = useTranslations("yt");
  const [selected, setSelected] = useState<string | null>(thumbs[0]?.thumbnail_id ?? null);
  const [wishes, setWishes] = useState("");
  const [aiBg, setAiBg] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/tenants/${tenantId}/youtube`;
  const current = thumbs.find((x) => x.thumbnail_id === selected) ?? thumbs[0];

  const design = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ thumbnail_ids: string[] }>(`${base}/videos/${video.video_id}/thumbnails/design`, { method: "POST", body: { wishes, ai_backgrounds: aiBg } });
      setSelected(r.thumbnail_ids[0]);
      onChange();
    } catch (err) {
      setError(errorText(err, t("error")));
    } finally {
      setBusy(false);
    }
  }, [base, video.video_id, wishes, aiBg, onChange, t]);

  async function blank() {
    setBusy(true);
    try {
      const r = await api<{ thumbnail_id: string }>(`${base}/thumbnails`, { method: "POST", body: { video_id: video.video_id, spec: { text: video.title.split(/\s+/).slice(0, 3).join(" ") } } });
      setSelected(r.thumbnail_id);
      onChange();
    } catch (err) {
      setError(errorText(err, t("error")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {canWork && (
        <section className="space-y-3 rounded-xl border border-border bg-surface p-4">
          <textarea rows={2} value={wishes} onChange={(e) => setWishes(e.target.value)} placeholder={t("thumbWishes")}
            className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none" dir="auto" />
          <div className="flex flex-wrap items-center gap-3">
            <CostButton cost={aiBg ? costs.thumbnail_ai * 3 : undefined} busy={busy} onClick={design}>{t("thumbDesign")}</CostButton>
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={aiBg} onChange={(e) => setAiBg(e.target.checked)} />{t("thumbAiBg")}</label>
            <CostButton variant="ghost" onClick={blank} disabled={busy}>{t("thumbBlank")}</CostButton>
          </div>
        </section>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
      {thumbs.length > 0 && (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {thumbs.map((x) => (
            <button key={x.thumbnail_id} type="button" onClick={() => setSelected(x.thumbnail_id)}
              className={`relative w-44 shrink-0 overflow-hidden rounded-lg border-2 ${current?.thumbnail_id === x.thumbnail_id ? "border-[#FF0000]" : "border-transparent"}`}>
              {x.status === "working" ? <div className="wf-skeleton aspect-video" /> : <img src={img(x)} alt="" className="aspect-video w-full object-cover" />}
              {x.status === "applied" && <span className="absolute left-1 top-1 rounded bg-success px-1.5 text-[10px] font-semibold text-white">{t("onYoutube")}</span>}
            </button>
          ))}
        </div>
      )}
      {current ? (
        <Editor key={current.thumbnail_id} tenantId={tenantId} thumb={current} video={video} channelName={channelName} costs={costs} canWork={canWork} onSaved={onChange} />
      ) : (
        <p className="text-sm text-muted">{t("thumbEmpty")}</p>
      )}
    </div>
  );
}
