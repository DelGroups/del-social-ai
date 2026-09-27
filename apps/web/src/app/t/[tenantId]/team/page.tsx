// The team: every agent with its role, duties, schedule, who it reports to, and what it is doing now.
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";

import { DailyActions } from "@/components/daily-actions";
import { PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { AGENT_COLOR } from "@/lib/agents";
import { apiGet, requireMe } from "@/lib/server-api";
import type { DailyRow, LiveInfo } from "@/lib/types";

const ACTIVE = ["team_lead", "market_researcher", "media_analyst", "copywriter", "brand_guardian", "visual_editor", "publisher"] as const;
const COMING = ["planner", "visual_designer", "community", "analyst", "cmo", "ads", "video"] as const;
const LETTER: Record<string, string> = {
  team_lead: "R", market_researcher: "B", media_analyst: "Ş", copywriter: "K", brand_guardian: "N", visual_editor: "V", publisher: "P",
};

export default async function TeamPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const t = await getTranslations("roster");
  const ta = await getTranslations("team");
  const [{ data: live }, { data: reports }] = await Promise.all([
    apiGet<LiveInfo>(`/tenants/${tenantId}/team/live`),
    apiGet<DailyRow[]>(`/tenants/${tenantId}/daily?limit=4`),
  ]);
  const state = Object.fromEntries((live?.agents ?? []).map((a) => [a.agent, a]));
  const last = (kind: string) => reports?.find((r) => r.kind === kind);
  const canRun = membership.role === "owner" || membership.role === "admin";

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <PageTitle>{t("title")}</PageTitle>
          <p className="-mt-4 max-w-2xl text-sm text-muted">{t("intro")}</p>
        </div>
        {canRun && <DailyActions tenantId={tenantId} />}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {ACTIVE.map((key) => {
          const a = state[key];
          const working = a?.state === "working";
          const report = key === "market_researcher" ? last("market") : key === "team_lead" ? last("briefing") : undefined;
          return (
            <section key={key} className={`flex flex-col gap-3 rounded-xl border bg-surface p-4 ${working ? "border-accent" : "border-border"}`}>
              <div className="flex items-center gap-3">
                <span
                  className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl text-lg font-semibold text-white ${working ? "ls-busy" : ""}`}
                  style={{ background: AGENT_COLOR[key] ?? "#777", ["--ls-c" as string]: AGENT_COLOR[key] ?? "#777" }}
                  aria-hidden="true"
                >
                  {LETTER[key]}
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="font-semibold">{ta(`agents.${key}`)}</h2>
                  <p className="text-xs text-muted">{t(`${key}.role`)}</p>
                </div>
                <span className={`rounded-full px-2 py-0.5 text-[11px] ${working ? "bg-accent/15 text-accent" : "bg-bg text-muted"}`}>
                  {working ? ta("working") : ta("doneToday", { count: a?.done_today ?? 0 })}
                </span>
              </div>
              {a?.activity && (
                <p className="rounded-md bg-bg px-3 py-2 text-xs" dir="auto">
                  <span className="text-muted">{a.last_at ? formatDateTime(a.last_at) : ""} · </span>
                  {a.activity}
                </p>
              )}
              <ul className="space-y-1 text-sm">
                {(t.raw(`${key}.duties`) as string[]).map((d) => (
                  <li key={d} className="flex gap-2">
                    <span className="text-accent">•</span>
                    <span>{d}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 text-xs text-muted">
                <span>🕘 {t(`${key}.schedule`)}</span>
                <span>↑ {key === "team_lead" ? t("reportsToYou") : t("reportsToLead")}</span>
                {report && (
                  <span className={report.status === "failed" ? "text-danger" : ""}>
                    {t("lastReport", { date: report.day, status: t(`status.${report.status}`) })}
                  </span>
                )}
              </div>
            </section>
          );
        })}
      </div>

      <h2 className="mb-3 mt-10 text-sm font-semibold">{t("comingTitle")}</h2>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {COMING.map((key) => (
          <section key={key} className="rounded-xl border border-dashed border-border p-4 opacity-80">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-medium">{ta(`studio.coming.${key}.name`)}</h3>
              <span className="rounded bg-bg px-1.5 text-[11px] text-muted">{ta("studio.soon")}</span>
            </div>
            <p className="mt-1 text-sm text-muted">{ta(`studio.coming.${key}.hint`)}</p>
          </section>
        ))}
      </div>
    </>
  );
}
