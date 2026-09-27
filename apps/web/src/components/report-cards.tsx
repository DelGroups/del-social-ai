"use client";

// Cards in the Team Room: the Team Lead's morning report (with suggestions the owner can start)
// and the Market Researcher's daily report.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { ApiError, api } from "@/lib/client-api";
import type { BriefingData, CardPayload } from "@/lib/types";

export function BriefingCard({
  tenantId,
  messageId,
  briefing,
  marketReportId,
  reportId,
  canAct,
  onChange,
}: {
  tenantId: string;
  messageId: string;
  briefing: BriefingData;
  marketReportId: string | null;
  reportId: string;
  canAct: boolean;
  onChange: () => void;
}) {
  const t = useTranslations("daily");
  const tc = useTranslations("common");
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function accept(i: number) {
    setBusy(i);
    setError(null);
    try {
      await api(`/tenants/${tenantId}/team/messages/${messageId}/suggestions/${i}/accept`, { method: "POST" });
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="w-full max-w-2xl space-y-3 rounded-lg border border-accent/60 bg-surface p-4 text-sm" dir="auto">
      <p className="text-xs font-semibold uppercase tracking-wide text-accent">{t("briefingTitle")}</p>
      <p className="font-medium">{briefing.greeting}</p>
      <p>{briefing.yesterday}</p>
      {briefing.market && (
        <div className="rounded-md bg-bg p-3">
          <p className="mb-1 text-xs font-semibold text-muted">{t("marketToday")}</p>
          <p>{briefing.market}</p>
          {marketReportId && (
            <Link href={`/t/${tenantId}/reports/${marketReportId}`} className="mt-1 inline-block text-xs text-accent underline">
              {t("openMarket")}
            </Link>
          )}
        </div>
      )}
      {briefing.today_plan.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold text-muted">{t("todayPlan")}</p>
          <ol className="list-inside list-decimal space-y-0.5">
            {briefing.today_plan.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ol>
        </div>
      )}
      {briefing.suggestions.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted">{t("suggestions")}</p>
          {briefing.suggestions.map((s, i) => (
            <div key={s.title} className="flex flex-wrap items-start gap-3 rounded-md border border-border p-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{s.title}</p>
                <p className="text-xs text-muted">{s.why}</p>
              </div>
              {s.action === "create_post" &&
                (s.status === "started" ? (
                  <Link href={`/t/${tenantId}/posts/${s.post_id}`} className="rounded-full bg-success/15 px-2.5 py-1 text-xs text-success">
                    ✓ {t("started.post")}
                  </Link>
                ) : canAct ? (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => accept(i)}
                    className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-text disabled:opacity-50"
                  >
                    {busy === i ? "…" : t("doIt")}
                  </button>
                ) : null)}
            </div>
          ))}
        </div>
      )}
      {briefing.questions.length > 0 && (
        <div className="rounded-md bg-accent/10 p-3">
          <p className="mb-1 text-xs font-semibold text-accent">{t("questions")}</p>
          {briefing.questions.map((q) => (
            <p key={q}>❓ {q}</p>
          ))}
          <p className="mt-1 text-xs text-muted">{t("answerInChat")}</p>
        </div>
      )}
      {error && <p className="text-danger">{error}</p>}
      <Link href={`/t/${tenantId}/reports/${reportId}`} className="inline-block text-xs text-muted underline">
        {t("fullReport")}
      </Link>
    </div>
  );
}

export function MarketCard({ tenantId, payload }: { tenantId: string; payload: Extract<CardPayload, { type: "market" }> }) {
  const t = useTranslations("daily");
  return (
    <div className="w-full max-w-2xl space-y-2 rounded-lg border border-border bg-surface p-4 text-sm" dir="auto">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("marketTitle")}</p>
      <p className="font-medium">📊 {payload.headline}</p>
      <p className="text-xs text-muted">{t("ideasCount", { count: payload.ideas })}</p>
      {payload.new_competitors && payload.new_competitors.length > 0 && (
        <p className="rounded-md bg-success/10 px-3 py-2 text-xs">🔎 {t("newCompetitors", { list: payload.new_competitors.join(", ") })}</p>
      )}
      {payload.questions.map((q) => (
        <p key={q} className="rounded-md bg-accent/10 px-3 py-2">❓ {q}</p>
      ))}
      <Link href={`/t/${tenantId}/reports/${payload.report_id}`} className="inline-block rounded-md border border-border px-3 py-1.5 text-xs hover:border-accent">
        {t("openMarket")}
      </Link>
    </div>
  );
}
