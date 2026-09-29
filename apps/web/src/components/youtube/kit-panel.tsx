"use client";

// Publishing kit of one video: the team writes three titles, a description with chapters, tags,
// hashtags, translations and a comment; the owner picks, edits and sends it to YouTube.
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { YtDraft, YtVideo } from "@/lib/youtube";

import { CostButton, errorText } from "./common";

type Chosen = NonNullable<YtDraft["chosen"]>;
type Publish = { mode: "keep" | "public" | "unlisted" | "private" | "schedule"; at: string };

function Score({ value }: { value: number }) {
  const r = 26, c = 2 * Math.PI * r;
  const color = value >= 75 ? "var(--success)" : value >= 50 ? "var(--accent)" : "var(--danger)";
  return (
    <svg viewBox="0 0 64 64" className="h-16 w-16" aria-label={`SEO ${value}`}>
      <circle cx="32" cy="32" r={r} fill="none" stroke="var(--border)" strokeWidth="6" />
      <circle cx="32" cy="32" r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round" strokeDasharray={c}
        strokeDashoffset={c * (1 - value / 100)} transform="rotate(-90 32 32)" className="transition-all duration-700" />
      <text x="32" y="37" textAnchor="middle" fontSize="16" fontWeight="700" fill="currentColor">{value}</text>
    </svg>
  );
}

export function KitPanel({ tenantId, video, drafts, canWork, onChange, costs }: {
  tenantId: string; video: YtVideo; drafts: YtDraft[]; canWork: boolean; onChange: () => void; costs: Record<string, number>;
}) {
  const t = useTranslations("yt");
  const draft = drafts[0];
  const [opts, setOpts] = useState({ tone: "", keywords: "", avoid: "" });
  const [ch, setCh] = useState<Chosen | null>(draft?.chosen ?? null);
  const [publish, setPublish] = useState<Publish>({ mode: "keep", at: "" });
  const [postComment, setPostComment] = useState(false);
  const [playlist, setPlaylist] = useState("");
  const [playlists, setPlaylists] = useState<{ playlist_id: string; title: string }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const base = `/tenants/${tenantId}/youtube`;

  useEffect(() => {
    setCh(draft?.chosen ?? null);
  }, [draft?.draft_id, draft?.status]);
  useEffect(() => {
    if (draft?.status === "ready") api<{ playlist_id: string; title: string }[]>(`${base}/playlists`).then(setPlaylists).catch(() => setPlaylists([]));
  }, [draft?.status, base]);

  async function make() {
    setBusy("make");
    setMsg(null);
    try {
      await api(`${base}/videos/${video.video_id}/kit`, { method: "POST", body: opts });
      onChange();
    } catch (err) {
      setMsg({ tone: "err", text: errorText(err, t("error")) });
    } finally {
      setBusy(null);
    }
  }
  async function apply() {
    if (!draft || !ch) return;
    if (!confirm(t("kitConfirm"))) return;
    setBusy("apply");
    setMsg(null);
    try {
      await api(`${base}/drafts/${draft.draft_id}/apply`, {
        method: "POST",
        body: { ...ch, post_comment: postComment, playlist_id: playlist || null,
          publish: { mode: publish.mode, at: publish.mode === "schedule" && publish.at ? new Date(publish.at).toISOString() : null } },
      });
      setMsg({ tone: "ok", text: t("kitApplied") });
      onChange();
    } catch (err) {
      setMsg({ tone: "err", text: errorText(err, t("error")) });
    } finally {
      setBusy(null);
    }
  }

  const field = "w-full rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none";
  const out = draft?.output;
  return (
    <div className="space-y-4">
      {canWork && (
        <section className="space-y-3 rounded-xl border border-border bg-surface p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <input value={opts.keywords} onChange={(e) => setOpts({ ...opts, keywords: e.target.value })} placeholder={t("kitKeywords")} className={field} />
            <input value={opts.tone} onChange={(e) => setOpts({ ...opts, tone: e.target.value })} placeholder={t("kitTone")} className={field} />
            <input value={opts.avoid} onChange={(e) => setOpts({ ...opts, avoid: e.target.value })} placeholder={t("kitAvoid")} className={field} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <CostButton cost={costs.metadata} busy={busy === "make" || draft?.status === "running"} onClick={make}>
              {draft ? t("kitAgain") : t("kitMake")}
            </CostButton>
            <p className="text-xs text-muted">{video.has_captions ? t("kitWithSubtitles") : t("kitNoSubtitles")}</p>
          </div>
        </section>
      )}
      {msg && <p className={`text-sm ${msg.tone === "ok" ? "text-success" : "text-danger"}`}>{msg.text}</p>}
      {!draft && <p className="text-sm text-muted">{t("kitEmpty")}</p>}
      {draft?.status === "running" && (
        <div className="space-y-2 rounded-xl border border-border bg-surface p-4">
          {[0, 1, 2].map((i) => <div key={i} className="wf-skeleton h-4 rounded" style={{ width: `${90 - i * 20}%` }} />)}
          <p className="text-xs text-muted">{t("kitWorking")}</p>
        </div>
      )}
      {draft?.status === "failed" && <p className="text-sm text-danger">{draft.error}</p>}
      {out && ch && (
        <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
          <div className="space-y-4">
            <section className="space-y-2 rounded-xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t("kitTitles")}</h3>
              {out.titles.map((o) => (
                <label key={o.text} className={`flex cursor-pointer gap-3 rounded-lg border p-3 text-sm ${ch.title === o.text ? "border-accent bg-accent/5" : "border-border"}`}>
                  <input type="radio" checked={ch.title === o.text} onChange={() => setCh({ ...ch, title: o.text })} />
                  <span className="flex-1">
                    <b className="block" dir="auto">{o.text}</b>
                    <span className="text-xs text-muted">{t(`titleStyle.${o.style}`)} · {o.text.length} · <span dir="auto">{o.why}</span></span>
                  </span>
                </label>
              ))}
              <input value={ch.title} maxLength={100} onChange={(e) => setCh({ ...ch, title: e.target.value })} className={field} dir="auto" />
            </section>
            <section className="space-y-2 rounded-xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t("kitDescription")}</h3>
              <textarea rows={12} value={ch.description} maxLength={5000} onChange={(e) => setCh({ ...ch, description: e.target.value })} className={`${field} font-mono text-xs`} dir="auto" />
              <p className="text-right text-[11px] text-muted">{ch.description.length} / 5000</p>
            </section>
            <section className="space-y-2 rounded-xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t("kitTags")}</h3>
              <div className="flex flex-wrap gap-1.5">
                {ch.tags.map((tag) => (
                  <span key={tag} className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-xs">
                    {tag}
                    <button type="button" onClick={() => setCh({ ...ch, tags: ch.tags.filter((x) => x !== tag) })} className="text-muted" aria-label="×">×</button>
                  </span>
                ))}
              </div>
              <input placeholder={t("kitAddTag")} className={field} onKeyDown={(e) => {
                const v = (e.target as HTMLInputElement).value.trim();
                if (e.key === "Enter" && v) { e.preventDefault(); setCh({ ...ch, tags: [...ch.tags, v] }); (e.target as HTMLInputElement).value = ""; }
              }} />
            </section>
            {ch.translations.length > 0 && (
              <section className="space-y-3 rounded-xl border border-border bg-surface p-4">
                <h3 className="text-sm font-semibold">{t("kitTranslations")}</h3>
                {ch.translations.map((tr, i) => (
                  <div key={tr.language} className="space-y-1.5">
                    <span className="rounded bg-bg px-1.5 text-xs uppercase">{tr.language}</span>
                    <input value={tr.title} onChange={(e) => setCh({ ...ch, translations: ch.translations.map((x, j) => j === i ? { ...x, title: e.target.value } : x) })} className={field} />
                    <textarea rows={3} value={tr.description} onChange={(e) => setCh({ ...ch, translations: ch.translations.map((x, j) => j === i ? { ...x, description: e.target.value } : x) })} className={field} />
                  </div>
                ))}
              </section>
            )}
            <section className="space-y-2 rounded-xl border border-border bg-surface p-4">
              <h3 className="text-sm font-semibold">{t("kitComment")}</h3>
              <textarea rows={2} value={ch.comment} onChange={(e) => setCh({ ...ch, comment: e.target.value })} className={field} dir="auto" />
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={postComment} onChange={(e) => setPostComment(e.target.checked)} />{t("kitPostComment")}</label>
            </section>
          </div>

          <aside className="space-y-4">
            {draft.seo && (
              <section className="space-y-2 rounded-xl border border-border bg-surface p-4">
                <div className="flex items-center gap-3"><Score value={draft.seo.score} /><div><b className="text-sm">SEO</b>
                  {draft.seo.main_keyword && <p className="text-xs text-muted">{t("kitKeyword")}: {draft.seo.main_keyword}</p>}</div></div>
                <ul className="space-y-1 text-xs">
                  {Object.entries(draft.seo.checks).map(([k, ok]) => (
                    <li key={k} className="flex gap-2"><span className={ok ? "text-success" : "text-danger"}>{ok ? "✓" : "✗"}</span>{t(`seo.${k}`)}</li>
                  ))}
                </ul>
              </section>
            )}
            {out.chapters_timed.length > 0 && (
              <section className="space-y-1 rounded-xl border border-border bg-surface p-4 text-xs">
                <h3 className="mb-1 text-sm font-semibold">{t("kitChapters")}</h3>
                {out.chapters_timed.map((c) => <p key={c.time}><b className="tabular-nums text-[#FF4D4D]">{c.time}</b> <span dir="auto">{c.title}</span></p>)}
              </section>
            )}
            <section className="space-y-3 rounded-xl border border-border bg-surface p-4 text-sm">
              <h3 className="font-semibold">{t("kitPublish")}</h3>
              <select value={publish.mode} onChange={(e) => setPublish({ ...publish, mode: e.target.value as Publish["mode"] })} className={field}>
                {(["keep", "public", "unlisted", "private", "schedule"] as const).map((m) => <option key={m} value={m}>{t(`publish.${m}`)}</option>)}
              </select>
              {publish.mode === "schedule" && <input type="datetime-local" value={publish.at} onChange={(e) => setPublish({ ...publish, at: e.target.value })} className={field} />}
              {playlists.length > 0 && (
                <select value={playlist} onChange={(e) => setPlaylist(e.target.value)} className={field}>
                  <option value="">{t("kitNoPlaylist")}</option>
                  {playlists.map((p) => <option key={p.playlist_id} value={p.playlist_id}>{p.title}</option>)}
                </select>
              )}
              {canWork && <CostButton busy={busy === "apply"} onClick={apply}>{t("kitApply")}</CostButton>}
              {draft.applied_at && <p className="text-xs text-success">{t("kitAppliedAt", { at: formatDateTime(draft.applied_at) })}</p>}
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
