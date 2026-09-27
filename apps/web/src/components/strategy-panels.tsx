"use client";

// Goals (with the owner's decisions) and the competitors the team watches.
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "@/lib/client-api";
import { formatDate } from "@/lib/prefs";
import type { CompetitorInfo, GoalInfo } from "@/lib/types";

import { GoalRow } from "./meeting-card";

export function GoalsPanel({ tenantId, canDecide }: { tenantId: string; canDecide: boolean }) {
  const t = useTranslations("goals");
  const [goals, setGoals] = useState<GoalInfo[] | null>(null);
  const load = useCallback(async () => {
    try {
      setGoals(await api<GoalInfo[]>(`/tenants/${tenantId}/goals`));
    } catch {
      setGoals([]);
    }
  }, [tenantId]);
  useEffect(() => {
    load();
  }, [load]);
  if (!goals) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold">{t("title")}</h2>
      {goals.length === 0 ? (
        <p className="text-sm text-muted">{t("none")}</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {goals.map((g) => <GoalRow key={g.goal_id} tenantId={tenantId} goal={g} canDecide={canDecide} onChange={load} />)}
        </div>
      )}
    </section>
  );
}

export function CompetitorsPanel({ tenantId, canManage }: { tenantId: string; canManage: boolean }) {
  const t = useTranslations("competitors");
  const tc = useTranslations("common");
  const [rows, setRows] = useState<CompetitorInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api<CompetitorInfo[]>(`/tenants/${tenantId}/competitors`));
    } catch {
      setRows([]);
    }
  }, [tenantId]);
  useEffect(() => {
    load();
  }, [load]);

  async function toggle(c: CompetitorInfo) {
    setError(null);
    try {
      await api(`/tenants/${tenantId}/competitors/${c.competitor_id}`, { method: "PATCH", body: { status: c.status === "ignored" ? "active" : "ignored" } });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    }
  }

  if (!rows) return null;
  const tone = { active: "text-success", invalid: "text-danger", inactive: "text-muted", ignored: "text-muted" } as const;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted">{t("hint")}</p>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">{t("none")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="py-1 pr-3 font-normal">{t("account")}</th>
                <th className="py-1 pr-3 font-normal">{t("source")}</th>
                <th className="py-1 pr-3 font-normal">{t("state")}</th>
                <th className="py-1 pr-3 text-right font-normal">{t("followers")}</th>
                <th className="py-1 pr-3 font-normal">{t("lastPost")}</th>
                <th className="py-1 font-normal" />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.competitor_id} className={`border-t border-border ${c.status === "ignored" ? "opacity-50" : ""}`}>
                  <td className="py-1.5 pr-3">
                    <a href={`https://instagram.com/${c.username}`} target="_blank" rel="noreferrer" className="hover:text-accent">@{c.username}</a>
                    {c.name && <span className="ml-1 text-xs text-muted">{c.name}</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-xs">
                    <span className={`rounded-full px-2 py-0.5 ${c.source === "discovered" ? "bg-success/15 text-success" : "bg-bg text-muted"}`}>{t(`src.${c.source}`)}</span>
                  </td>
                  <td className={`py-1.5 pr-3 text-xs ${tone[c.status]}`} title={c.note}>{t(`st.${c.status}`)}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{c.followers?.toLocaleString() ?? "—"}</td>
                  <td className="py-1.5 pr-3 text-xs text-muted">{c.last_post_at ? formatDate(c.last_post_at) : "—"}</td>
                  <td className="py-1.5 text-right">
                    {canManage && (
                      <button type="button" onClick={() => toggle(c)} className="text-xs text-muted underline hover:text-text">
                        {c.status === "ignored" ? t("watch") : t("ignore")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  );
}
