"use client";

// Platform admin: every company's package, this month's usage, our AI cost and margin; assign packages.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Alert, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import { formatDate } from "@/lib/prefs";
import type { TenantOverview } from "@/lib/types";

const PLANS = ["basic", "pro", "enterprise"] as const;
const MONTHS = ["1", "3", "6", "12", "none"] as const;

function AssignForm({ row, onDone }: { row: TenantOverview; onDone: () => void }) {
  const t = useTranslations("platform");
  const tc = useTranslations("common");
  const [plan, setPlan] = useState(row.open_request_plan ?? row.plan_id ?? "basic");
  const [months, setMonths] = useState<string>("1");
  const [video, setVideo] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!confirm(t("assignConfirm", { name: row.name, plan: t(`plans.${plan}`) }))) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/platform/tenants/${row.tenant_id}/subscription`, {
        method: "PUT",
        body: { plan_id: plan, months: months === "none" ? null : Number(months), extra_video_credits: video },
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setBusy(false);
    }
  }

  const cls = "rounded-md border border-border bg-bg px-2 py-1 text-sm";
  return (
    <form onSubmit={save} className="flex flex-wrap items-end gap-2 rounded-md bg-bg/60 p-2">
      <label className="text-xs text-muted">
        {t("plan")}
        <select value={plan} onChange={(e) => setPlan(e.target.value)} className={`mt-1 block ${cls}`}>
          {PLANS.map((p) => (
            <option key={p} value={p}>{t(`plans.${p}`)}</option>
          ))}
        </select>
      </label>
      <label className="text-xs text-muted">
        {t("months")}
        <select value={months} onChange={(e) => setMonths(e.target.value)} className={`mt-1 block ${cls}`}>
          {MONTHS.map((m) => (
            <option key={m} value={m}>{m === "none" ? t("noEnd") : t("monthsN", { n: Number(m) })}</option>
          ))}
        </select>
      </label>
      <label className="text-xs text-muted">
        {t("extraVideo")}
        <input type="number" min={0} max={1000} value={video} onChange={(e) => setVideo(Number(e.target.value) || 0)} className={`mt-1 block w-20 ${cls}`} />
      </label>
      <button type="submit" disabled={busy} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-text disabled:opacity-50">
        {t("assign")}
      </button>
      <p className="w-full text-xs text-muted">{t("assignNote")}</p>
      {error && <p className="w-full text-sm text-danger">{error}</p>}
    </form>
  );
}

export function PlatformTenants() {
  const t = useTranslations("platform");
  const [rows, setRows] = useState<TenantOverview[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api<TenantOverview[]>("/platform/tenants"));
      setError(false);
    } catch {
      setError(true);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const usd = (v: string | null) => (v === null ? "—" : `$${Number(v).toFixed(2)}`);
  return (
    <Card title={t("tenantsTitle")}>
      {error && <Alert tone="error">{t("loadError")}</Alert>}
      {rows && rows.length === 0 && <p className="text-sm text-muted">{t("noTenants")}</p>}
      <ul className="divide-y divide-border">
        {(rows ?? []).map((r) => (
          <li key={r.tenant_id} className="space-y-2 py-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              <span className="min-w-40 font-semibold">{r.name}</span>
              <span>{r.plan_id ? t(`plans.${r.plan_id}`) : <span className="text-danger">{t("noPlan")}</span>}</span>
              <span className="text-muted">
                {r.expires_at ? t("until", { date: formatDate(r.expires_at) }) : r.plan_id ? t("noEnd") : ""}
              </span>
              <span className="tabular-nums text-muted">
                {t("posts", { used: r.posts_published, scheduled: r.posts_scheduled, limit: r.posts_limit ?? "∞" })}
              </span>
              <span className="text-muted">{t("counts", { members: r.members, channels: r.channels })}</span>
              <span className="tabular-nums">{t("cost", { cost: usd(r.ai_cost_month_usd) })}</span>
              <span className={`tabular-nums ${r.margin_month_usd !== null && Number(r.margin_month_usd) < 0 ? "text-danger" : "text-success"}`}>
                {t("margin", { margin: usd(r.margin_month_usd) })}
              </span>
              {r.open_request_plan && (
                <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">
                  {t("requestBadge", { plan: t(`plans.${r.open_request_plan}`) })}
                </span>
              )}
              <button type="button" onClick={() => setOpen(open === r.tenant_id ? null : r.tenant_id)} className="ml-auto text-xs text-accent underline">
                {t("change")}
              </button>
            </div>
            {open === r.tenant_id && (
              <AssignForm
                row={r}
                onDone={() => {
                  setOpen(null);
                  load();
                }}
              />
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
