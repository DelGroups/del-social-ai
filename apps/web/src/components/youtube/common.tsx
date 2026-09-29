"use client";

// Pieces shared by the YouTube Studio pages: loading the dashboard, the credit pill, report text,
// "costs N credits" buttons and the empty states (no add-on, no channel).
import { useTranslations } from "next-intl";
import Link from "next/link";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { LogoOrb } from "@/components/channel-cards";
import { ApiError, api } from "@/lib/client-api";
import type { YtDashboard, YtReport } from "@/lib/youtube";

export function useDashboard(tenantId: string) {
  const [data, setData] = useState<YtDashboard | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await api<YtDashboard>(`/tenants/${tenantId}/youtube`));
    } catch {
      /* keep the last view */
    }
  }, [tenantId]);
  useEffect(() => {
    load();
  }, [load]);
  return { data, load };
}

/** Re-run `fn` every few seconds while `active` is true (reports and designs being made). */
export function usePoll(active: boolean, fn: () => void, ms = 3000) {
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(fn, ms);
    return () => clearInterval(timer);
  }, [active, fn, ms]);
}

export function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function CreditPill({ total }: { total: number }) {
  const t = useTranslations("yt");
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-bg px-3 py-1 text-xs">
      <span className="h-2 w-2 rounded-full bg-[#FF0000] ch-dot" />
      <b className="tabular-nums">{total}</b> {t("credits")}
    </span>
  );
}

/** A button that says what it costs; the API refuses (402) when credits are short. */
export function CostButton({
  cost, onClick, busy, children, variant = "primary", disabled,
}: { cost?: number; onClick: () => void; busy?: boolean; children: ReactNode; variant?: "primary" | "ghost"; disabled?: boolean }) {
  const t = useTranslations("yt");
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      className={`inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition disabled:opacity-50 ${
        variant === "primary" ? "bg-accent text-accent-text hover:opacity-90" : "border border-border hover:border-accent"
      }`}
    >
      {busy ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" /> : null}
      {children}
      {cost ? <span className="rounded-full bg-black/15 px-1.5 text-[11px] tabular-nums">{t("cost", { n: cost })}</span> : null}
    </button>
  );
}

export function ReportBody({ report }: { report: YtReport }) {
  const t = useTranslations("yt");
  if (report.status === "running") {
    return (
      <div className="space-y-2">
        <div className="wf-skeleton h-3 w-3/4 rounded" />
        <div className="wf-skeleton h-3 w-1/2 rounded" />
        <p className="text-xs text-muted">{t("working")}</p>
      </div>
    );
  }
  if (report.status === "failed") return <p className="text-sm text-danger">{report.error}</p>;
  const o = report.output ?? {};
  return (
    <div className="space-y-2 text-sm">
      {o.headline && <p className="font-semibold">{o.headline}</p>}
      {o.summary && <p className="text-muted" dir="auto">{o.summary}</p>}
      {Array.isArray(o.highlights) && o.highlights.length > 0 && (
        <ul className="space-y-1">
          {o.highlights.map((h: string) => (
            <li key={h} className="flex gap-2"><span className="text-[#FF4D4D]">▲</span><span dir="auto">{h}</span></li>
          ))}
        </ul>
      )}
      {Array.isArray(o.actions) && o.actions.length > 0 && (
        <div className="rounded-md bg-bg p-2.5">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t("todo")}</p>
          <ul className="space-y-1">
            {o.actions.map((a: string) => <li key={a} className="flex gap-2"><span>→</span><span dir="auto">{a}</span></li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function NoAddon({ tenantId }: { tenantId: string }) {
  const t = useTranslations("yt");
  return (
    <div className="ch-card relative flex flex-col items-center gap-4 overflow-hidden rounded-2xl border border-border bg-surface p-8 text-center" style={{ ["--ch-glow" as string]: "#FF0000" }}>
      <LogoOrb channel="youtube" live />
      <h2 className="text-xl font-semibold">{t("upsell.title")}</h2>
      <p className="max-w-lg text-sm text-muted">{t("upsell.text")}</p>
      <Link href={`/t/${tenantId}/plan`} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-text">{t("upsell.cta")}</Link>
    </div>
  );
}

export function NotConnected({ tenantId, configured }: { tenantId: string; configured: boolean }) {
  const t = useTranslations("yt");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function connect() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await api<{ url: string }>(`/tenants/${tenantId}/connections/google/start`, { method: "POST" });
      window.location.href = url;
    } catch (err) {
      setError(errorText(err, t("error")));
      setBusy(false);
    }
  }
  return (
    <div className="ch-card relative flex flex-col items-center gap-4 overflow-hidden rounded-2xl border border-border bg-surface p-8 text-center" style={{ ["--ch-glow" as string]: "#FF0000" }}>
      <LogoOrb channel="youtube" live />
      <h2 className="text-xl font-semibold">{t("connect.title")}</h2>
      <p className="max-w-lg text-sm text-muted">{t("connect.text")}</p>
      {configured ? (
        <button type="button" onClick={connect} disabled={busy} className="inline-flex items-center gap-2 rounded-md bg-white px-4 py-2 text-sm font-medium text-[#1f1f1f] shadow disabled:opacity-60">
          <svg viewBox="0 0 48 48" className="h-4 w-4" aria-hidden="true">
            <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z" />
            <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
            <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
            <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.9z" />
          </svg>
          {t("connect.button")}
        </button>
      ) : (
        <p className="rounded-md bg-bg px-3 py-2 text-sm text-muted">{t("connect.notConfigured")}</p>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  );
}

/** Wraps a studio page: shows the right empty state until the add-on and a channel are there. */
export function StudioGate({ tenantId, data, children, requireChannel = true }: {
  tenantId: string; data: YtDashboard | null; children: ReactNode; requireChannel?: boolean;
}) {
  if (!data) return <div className="wf-skeleton h-40 rounded-2xl" />;
  if (!data.addon.active) return <NoAddon tenantId={tenantId} />;
  if (requireChannel && !data.connection) return <NotConnected tenantId={tenantId} configured={data.google_configured} />;
  return <>{children}</>;
}
