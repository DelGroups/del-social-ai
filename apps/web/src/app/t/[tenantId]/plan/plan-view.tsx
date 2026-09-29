"use client";

// The package: allowances used this month, validity, and the three packages to compare and request.
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AddonPanel } from "@/components/addon-panel";
import { Alert, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import { formatDate } from "@/lib/prefs";
import type { Meter, PlanInfo, PlanStatus } from "@/lib/types";

const FEATURES = ["auto_support", "sales_agent", "weekly_report", "erp"] as const;

function Bar({ label, meter, hint, reserved = 0 }: { label: string; meter: Meter; hint?: string; reserved?: number }) {
  const t = useTranslations("plan");
  const limit = meter.limit;
  const pct = (n: number) => (limit ? Math.min(100, (n / limit) * 100) : 0);
  const full = limit !== null && meter.used >= limit;
  const warn = limit !== null && !full && meter.used >= 0.8 * limit;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">{label}</span>
        <span className={`tabular-nums ${full ? "text-danger" : warn ? "text-accent" : "text-muted"}`}>
          {limit === null ? t("usedUnlimited", { used: meter.used }) : t("usedOf", { used: meter.used, limit })}
        </span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-bg" aria-hidden="true">
        {limit === null ? (
          <span className="h-full w-full bg-success/30" />
        ) : (
          <>
            <span className={`h-full ${full ? "bg-danger" : warn ? "bg-accent" : "bg-success"}`} style={{ width: `${pct(meter.used - reserved)}%` }} />
            {reserved > 0 && <span className="h-full bg-success/40" style={{ width: `${pct(reserved)}%` }} />}
          </>
        )}
      </div>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

function Limits({ p }: { p: PlanInfo }) {
  const t = useTranslations("plan");
  const n = (v: number | null, key: string) => (v === null ? t(`${key}Unlimited`) : t(key, { n: v }));
  return (
    <ul className="space-y-1 text-sm">
      <li>{n(p.posts_per_month, "postsN")}</li>
      <li>{n(p.channels, "channelsN")}</li>
      <li>{n(p.users, "usersN")}</li>
      <li>{n(p.video_credits, "videoN")}</li>
      {FEATURES.map((f) => (
        <li key={f} className={p.features[f] ? "" : "text-muted line-through decoration-muted/50"}>
          {p.features[f] ? "✓ " : "– "}
          {t(`feature.${f}`)}
        </li>
      ))}
      {!p.features.auto_support && <li className="text-xs text-muted">{t("draftReplies")}</li>}
    </ul>
  );
}

export function PlanView({ tenantId, initial, canBuy }: { tenantId: string; initial: PlanStatus; canBuy: boolean }) {
  const t = useTranslations("plan");
  const tc = useTranslations("common");
  const router = useRouter();
  const [plan, setPlan] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = plan.plan;

  async function request(planId: string) {
    setBusy(planId);
    setError(null);
    try {
      setPlan(await api<PlanStatus>(`/tenants/${tenantId}/plan/requests`, { method: "POST", body: { plan_id: planId } }));
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setBusy(null);
    }
  }

  const youtubeOnly = !current && plan.addons.some((a) => a.active);
  const addons = plan.addons.map((a) => (
    <AddonPanel key={a.addon_id} tenantId={tenantId} addon={a} canBuy={canBuy} onChange={(p) => { setPlan(p); router.refresh(); }} />
  ));
  const days = plan.expires_at ? Math.max(0, Math.ceil((Date.parse(plan.expires_at) - Date.now()) / 86_400_000)) : null;

  return (
    <div className="space-y-6">
      {youtubeOnly && addons}
      {current ? (
        <Card>
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted">{t("current")}</p>
              <p className="text-2xl font-semibold">{current.name}</p>
              <p className="text-sm text-muted">{t("price", { price: Number(current.price_azn).toLocaleString() })}</p>
            </div>
            <div className="text-right text-sm">
              {plan.period_start && plan.period_end && (
                <p className="text-muted">{t("period", { start: formatDate(plan.period_start), end: formatDate(plan.period_end) })}</p>
              )}
              <p className={plan.state === "expired" ? "text-danger" : days !== null && days <= 7 ? "text-accent" : ""}>
                {plan.expires_at ? t("until", { date: formatDate(plan.expires_at), days: days ?? 0 }) : t("noEnd")}
              </p>
            </div>
          </div>
          {plan.state === "expired" && <div className="mb-4"><Alert tone="error">{t("expiredLong")}</Alert></div>}
          <div className="grid gap-5 sm:grid-cols-2">
            <Bar
              label={t("meter.posts")}
              meter={plan.posts}
              reserved={plan.posts_scheduled}
              hint={t("meter.postsHint", { published: plan.posts_published, scheduled: plan.posts_scheduled })}
            />
            <Bar label={t("meter.drafts")} meter={plan.drafts} hint={t("meter.draftsHint")} />
            <Bar label={t("meter.video")} meter={plan.video} hint={t("meter.videoHint")} />
            <Bar label={t("meter.channels")} meter={plan.channels} />
            <Bar label={t("meter.users")} meter={plan.users} />
          </div>
        </Card>
      ) : youtubeOnly ? null : (
        <Alert tone="error">{t("banner.none")}</Alert>
      )}

      {plan.open_request && (
        <Alert tone="success">
          {t("requested", {
            plan: plan.catalog.find((p) => p.plan_id === plan.open_request!.plan_id)?.name ?? plan.open_request.plan_id,
            date: formatDate(plan.open_request.created_at),
          })}
        </Alert>
      )}
      {error && <Alert tone="error">{error}</Alert>}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">{t("catalog")}</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {plan.catalog.map((p) => {
            const isCurrent = current?.plan_id === p.plan_id;
            const requested = plan.open_request?.plan_id === p.plan_id;
            return (
              <div key={p.plan_id} className={`flex flex-col gap-4 rounded-lg border bg-surface p-4 ${isCurrent ? "border-accent" : "border-border"}`}>
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-lg font-semibold">{p.name}</p>
                    {isCurrent && <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">{t("yours")}</span>}
                  </div>
                  <p className="text-sm text-muted">
                    {p.plan_id === "enterprise" ? t("priceFrom", { price: Number(p.price_azn).toLocaleString() }) : t("price", { price: Number(p.price_azn).toLocaleString() })}
                  </p>
                </div>
                <Limits p={p} />
                <div className="mt-auto">
                  {isCurrent ? (
                    plan.state === "expired" && canBuy ? (
                      <button type="button" disabled={busy !== null || requested} onClick={() => request(p.plan_id)} className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-text disabled:opacity-50">
                        {requested ? t("requestedShort") : t("renew")}
                      </button>
                    ) : null
                  ) : canBuy ? (
                    <button type="button" disabled={busy !== null || requested} onClick={() => request(p.plan_id)} className="w-full rounded-md border border-accent px-3 py-2 text-sm font-medium text-accent hover:bg-accent hover:text-accent-text disabled:opacity-50">
                      {requested ? t("requestedShort") : busy === p.plan_id ? "…" : t("request")}
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-muted">{canBuy ? t("paymentNote") : t("ownerOnly")}</p>
      </section>

      {!youtubeOnly && addons.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold">{t("addonsTitle")}</h2>
          {addons}
        </section>
      )}
    </div>
  );
}
