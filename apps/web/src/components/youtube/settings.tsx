"use client";

// Channel settings: what the channel is about (the team's brief), languages, report rhythm, links,
// and the competitor channels the ideas research watches.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { formatCount } from "@/components/channel-cards";
import { api } from "@/lib/client-api";
import type { YtCompetitor, YtSettings } from "@/lib/youtube";

import { CostButton, StudioGate, errorText, useDashboard } from "./common";

const LANGS = ["az", "ru", "en", "tr"] as const;

export function YtSettingsPage({ tenantId, canManage }: { tenantId: string; canWork: boolean; canManage?: boolean }) {
  const t = useTranslations("yt");
  const { data, load } = useDashboard(tenantId);
  const [s, setS] = useState<YtSettings | null>(null);
  const [rivals, setRivals] = useState<YtCompetitor[]>([]);
  const [add, setAdd] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/tenants/${tenantId}/youtube`;
  const loadRivals = useCallback(async () => {
    try {
      setRivals(await api<YtCompetitor[]>(`${base}/competitors`));
    } catch {
      setRivals([]);
    }
  }, [base]);
  useEffect(() => {
    if (data?.settings && !s) setS(data.settings);
    if (data?.connection && data.addon.active) loadRivals();
  }, [data, s, loadRivals]);

  async function save() {
    if (!s) return;
    setBusy(true);
    setMsg(null);
    try {
      setS(await api<YtSettings>(`${base}/settings`, { method: "PUT", body: s }));
      setMsg({ tone: "ok", text: t("saved") });
      load();
    } catch (err) {
      setMsg({ tone: "err", text: errorText(err, t("error")) });
    } finally {
      setBusy(false);
    }
  }
  async function addRivals() {
    const channels = add.split(/[\s,]+/).filter(Boolean);
    if (!channels.length) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ added: string[]; not_found: string[] }>(`${base}/competitors`, { method: "POST", body: { channels } });
      setMsg({ tone: r.not_found.length ? "err" : "ok", text: [r.added.length ? t("rivalsAdded", { list: r.added.join(", ") }) : "",
        r.not_found.length ? t("rivalsMissing", { list: r.not_found.join(", ") }) : ""].filter(Boolean).join(" ") });
      setAdd("");
      loadRivals();
    } catch (err) {
      setMsg({ tone: "err", text: errorText(err, t("error")) });
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-md border border-border bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none disabled:opacity-60";
  const disabled = !canManage;
  return (
    <StudioGate tenantId={tenantId} data={data}>
      {s && (
        <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
          <section className="space-y-4 rounded-xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold">{t("set.title")}</h2>
            <label className="block space-y-1 text-sm"><span className="font-medium">{t("set.about")}</span>
              <textarea rows={3} value={s.about} disabled={disabled} onChange={(e) => setS({ ...s, about: e.target.value })} placeholder={t("set.aboutHint")} className={field} dir="auto" />
            </label>
            <label className="block space-y-1 text-sm"><span className="font-medium">{t("set.audience")}</span>
              <textarea rows={2} value={s.audience} disabled={disabled} onChange={(e) => setS({ ...s, audience: e.target.value })} className={field} dir="auto" />
            </label>
            <label className="block space-y-1 text-sm"><span className="font-medium">{t("set.tone")}</span>
              <input value={s.tone} disabled={disabled} onChange={(e) => setS({ ...s, tone: e.target.value })} placeholder={t("set.toneHint")} className={field} dir="auto" />
            </label>
            <div className="space-y-1 text-sm">
              <span className="font-medium">{t("set.languages")}</span>
              <div className="flex flex-wrap gap-2">
                {LANGS.map((l) => {
                  const on = s.languages.includes(l);
                  return (
                    <button key={l} type="button" disabled={disabled || (on && s.languages.length === 1)}
                      onClick={() => setS({ ...s, languages: on ? s.languages.filter((x) => x !== l) : [...s.languages, l] })}
                      className={`rounded-full border px-3 py-1 text-xs ${on ? "border-accent bg-accent/10 text-accent" : "border-border text-muted"}`}>
                      {s.languages[0] === l ? "★ " : ""}{t(`lang.${l}`)}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-muted">{t("set.languagesHint")}</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <label className="space-y-1 text-sm"><span className="font-medium">{t("set.pulse")}</span>
                <select value={s.pulse_hours} disabled={disabled} onChange={(e) => setS({ ...s, pulse_hours: Number(e.target.value) as YtSettings["pulse_hours"] })} className={field}>
                  {[0, 3, 6, 12].map((h) => <option key={h} value={h}>{h ? t("set.everyHours", { n: h }) : t("set.off")}</option>)}
                </select>
              </label>
              <label className="space-y-1 text-sm"><span className="font-medium">{t("set.daily")}</span>
                <select value={s.daily_report ? s.daily_at : -1} disabled={disabled}
                  onChange={(e) => { const v = Number(e.target.value); setS({ ...s, daily_report: v >= 0, daily_at: v >= 0 ? v : s.daily_at }); }} className={field}>
                  <option value={-1}>{t("set.off")}</option>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{`${String(h).padStart(2, "0")}:00`}</option>)}
                </select>
              </label>
              <label className="space-y-1 text-sm"><span className="font-medium">{t("set.region")}</span>
                <input value={s.region} disabled={disabled} maxLength={2} onChange={(e) => setS({ ...s, region: e.target.value.toUpperCase() })} className={field} />
              </label>
            </div>
            <label className="block space-y-1 text-sm"><span className="font-medium">{t("set.reportLanguage")}</span>
              <select value={s.report_language} disabled={disabled} onChange={(e) => setS({ ...s, report_language: e.target.value as YtSettings["report_language"] })} className={field}>
                {(["auto", "az", "ru", "en", "fa"] as const).map((l) => <option key={l} value={l}>{t(`rlang.${l}`)}</option>)}
              </select>
            </label>
            <label className="block space-y-1 text-sm"><span className="font-medium">{t("set.links")}</span>
              <textarea rows={3} value={s.links} disabled={disabled} onChange={(e) => setS({ ...s, links: e.target.value })} placeholder={t("set.linksHint")} className={field} />
            </label>
            {canManage && <CostButton busy={busy} onClick={save}>{t("save")}</CostButton>}
            {msg && <p className={`text-sm ${msg.tone === "ok" ? "text-success" : "text-danger"}`}>{msg.text}</p>}
          </section>

          <section className="space-y-3 rounded-xl border border-border bg-surface p-5">
            <h2 className="text-sm font-semibold">{t("rivals")}</h2>
            <p className="text-xs text-muted">{t("rivalsHint")}</p>
            {canManage && (
              <div className="flex gap-2">
                <input value={add} onChange={(e) => setAdd(e.target.value)} placeholder="@channel, youtube.com/@…" className={field} />
                <CostButton variant="ghost" busy={busy} onClick={addRivals}>{t("add")}</CostButton>
              </div>
            )}
            <ul className="space-y-2">
              {rivals.map((r) => (
                <li key={r.competitor_id} className="flex items-center gap-3 rounded-lg bg-bg p-2 text-sm">
                  {r.avatar ? <img src={r.avatar} alt="" className="h-8 w-8 rounded-full" /> : <span className="h-8 w-8 rounded-full bg-surface" />}
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{r.title}</p>
                    <p className="text-xs text-muted"><bdi>{r.handle}</bdi> · {formatCount(r.subscribers)} {t("subscribers")}</p>
                  </div>
                  {canManage && (
                    <button type="button" onClick={async () => { await api(`${base}/competitors/${r.competitor_id}`, { method: "DELETE" }); loadRivals(); }}
                      className="text-xs text-muted underline">{t("remove")}</button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </StudioGate>
  );
}
