"use client";

// Package page: the YouTube Studio add-on — whether it's on, the credits left (this month's and
// bought ones), credit packs to ask for, what each piece of work costs, and the latest movements.
import { useTranslations } from "next-intl";
import { useState } from "react";

import { BrandLogo } from "@/lib/brand-icons";
import { ApiError, api } from "@/lib/client-api";
import { formatDate, formatDateTime } from "@/lib/prefs";
import type { AddonStatus, PlanStatus } from "@/lib/types";

export function AddonPanel({
  tenantId, addon, canBuy, onChange,
}: { tenantId: string; addon: AddonStatus; canBuy: boolean; onChange: (p: PlanStatus) => void }) {
  const t = useTranslations("addons");
  const tc = useTranslations("common");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask(kind: "addon" | "credits", item: string) {
    setBusy(item);
    setError(null);
    try {
      onChange(await api<PlanStatus>(`/tenants/${tenantId}/plan/purchases`, { method: "POST", body: { kind, item_id: item } }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setBusy(null);
    }
  }

  const monthlyPct = addon.monthly_credits ? Math.round((addon.monthly_left / addon.monthly_credits) * 100) : 0;
  const workLabel = (reason: string) => {
    const key = reason.startsWith("spend:") ? reason.slice(6) : reason;
    return t.has(`work.${key}`) ? t(`work.${key}`) : key;
  };

  return (
    <section className="ch-card relative space-y-4 overflow-hidden rounded-xl border border-border bg-surface p-5" style={{ ["--ch-glow" as string]: "#FF0000" }}>
      <div className="flex flex-wrap items-start gap-4">
        <div className="relative grid h-14 w-14 place-items-center" style={{ ["--ch-ring" as string]: "conic-gradient(#FF0000, #FF6A3D, #FF0000)", ["--ch-glow" as string]: "#FF0000" }}>
          <span className={`ch-ring absolute inset-0 rounded-full ${addon.active ? "" : "ch-still"}`} aria-hidden="true" />
          <span className="absolute inset-[3px] rounded-full bg-surface" aria-hidden="true" />
          <span className="ch-float relative"><BrandLogo channel="youtube" size={26} /></span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-muted">{t("kicker")}</p>
          <h2 className="text-xl font-semibold">{addon.name}</h2>
          <p className="text-sm text-muted">{t("price", { price: Number(addon.price_azn).toLocaleString(), credits: addon.monthly_credits })}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${addon.active ? "bg-success/15 text-success" : "bg-bg text-muted"}`}>
          {addon.active ? t("on") : t("off")}
        </span>
      </div>

      {!addon.active ? (
        <div className="space-y-3">
          <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
            {["thumbs", "texts", "reports", "review", "ideas", "comments", "editor", "generate"].map((k) => (
              <li key={k} className="flex gap-2"><span className="text-success">✓</span>{t(`does.${k}`)}</li>
            ))}
          </ul>
          {canBuy && (
            <button type="button" disabled={busy !== null || addon.open_request === addon.addon_id} onClick={() => ask("addon", addon.addon_id)}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text disabled:opacity-50">
              {addon.open_request === addon.addon_id ? t("requested") : t("ask")}
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-lg bg-bg p-3">
              <p className="text-xs text-muted">{t("total")}</p>
              <p className="text-3xl font-semibold tabular-nums">{addon.total}</p>
            </div>
            <div className="space-y-1.5 rounded-lg bg-bg p-3">
              <p className="flex justify-between text-xs text-muted"><span>{t("monthly")}</span><span className="tabular-nums text-text">{addon.monthly_left} / {addon.monthly_credits}</span></p>
              <div className="h-1.5 overflow-hidden rounded-full bg-surface"><div className="h-full rounded-full bg-success" style={{ width: `${monthlyPct}%` }} /></div>
              {addon.period_end && <p className="text-xs text-muted">{t("renews", { date: formatDate(addon.period_end) })}</p>}
            </div>
            <div className="rounded-lg bg-bg p-3">
              <p className="text-xs text-muted">{t("bought")}</p>
              <p className="text-xl font-semibold tabular-nums">{addon.purchased}</p>
              <p className="text-xs text-muted">{t("neverExpire")}</p>
            </div>
          </div>
          {addon.expires_at && <p className="text-xs text-muted">{t("until", { date: formatDate(addon.expires_at) })}</p>}

          <div className="space-y-2">
            <h3 className="text-sm font-semibold">{t("packs")}</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              {addon.packs.map((p) => {
                const requested = addon.open_request === p.pack_id;
                return (
                  <div key={p.pack_id} className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
                    <div>
                      <p className="font-semibold tabular-nums">{t("credits", { n: p.credits })}</p>
                      <p className="text-xs text-muted">{t("packPrice", { price: Number(p.price_azn).toLocaleString() })}</p>
                    </div>
                    {canBuy && (
                      <button type="button" disabled={busy !== null || requested} onClick={() => ask("credits", p.pack_id)}
                        className="rounded-md border border-accent px-3 py-1.5 text-xs font-medium text-accent hover:bg-accent hover:text-accent-text disabled:opacity-50">
                        {requested ? t("requested") : busy === p.pack_id ? "…" : t("buy")}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}

      <details className="text-sm">
        <summary className="cursor-pointer text-muted hover:text-text">{t("costsTitle")}</summary>
        <ul className="mt-2 grid gap-1 sm:grid-cols-2">
          {Object.entries(addon.costs).map(([k, v]) => (
            <li key={k} className="flex justify-between gap-3 border-b border-border py-1"><span>{workLabel(k)}</span><span className="tabular-nums text-muted">{t("credits", { n: v })}</span></li>
          ))}
        </ul>
      </details>

      {addon.history.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted hover:text-text">{t("history")}</summary>
          <ul className="mt-2 space-y-1">
            {addon.history.map((h, i) => (
              <li key={`${h.created_at}${i}`} className="flex justify-between gap-3 text-xs">
                <span className="text-muted tabular-nums">{formatDateTime(h.created_at)}</span>
                <span className="flex-1 truncate">{workLabel(h.reason)}</span>
                <span className={`tabular-nums font-medium ${h.delta > 0 ? "text-success" : ""}`}>{h.delta > 0 ? `+${h.delta}` : h.delta}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
