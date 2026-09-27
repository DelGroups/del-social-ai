// One daily report: the Market Researcher's findings with their evidence and the numbers code
// collected, or the Team Lead's morning report.
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { Alert, Card, PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { apiGet, requireMe } from "@/lib/server-api";
import type { BriefingData, CollectedAccount, DailyFull, Finding, MarketReportData, MeetingData } from "@/lib/types";

const TONE: Record<Finding["confidence"], string> = {
  high: "border-success text-success",
  medium: "border-accent text-accent",
  low: "border-border text-muted",
};

async function Findings({ title, items }: { title: string; items: Finding[] }) {
  const t = await getTranslations("daily");
  if (items.length === 0) return null;
  return (
    <Card title={title}>
      <ul className="space-y-3">
        {items.map((f) => (
          <li key={f.title} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{f.title}</span>
              <span className={`rounded-full border px-2 py-0.5 text-[11px] ${TONE[f.confidence]}`}>{t(`confidence.${f.confidence}`)}</span>
            </div>
            <p className="text-sm">{f.detail}</p>
            <p className="text-xs text-muted">↳ {f.evidence}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

async function Accounts({ own, competitors }: { own?: CollectedAccount | null; competitors: CollectedAccount[] }) {
  const t = await getTranslations("daily");
  const rows = [...(own ? [{ ...own, mine: true }] : []), ...competitors.map((c) => ({ ...c, mine: false }))];
  if (rows.length === 0) return null;
  return (
    <Card title={t("numbersTitle")}>
      <p className="mb-3 text-xs text-muted">{t("numbersHint")}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="text-xs text-muted">
            <tr>
              <th className="py-1 pr-3 font-normal">{t("col.account")}</th>
              <th className="py-1 pr-3 text-right font-normal">{t("col.followers")}</th>
              <th className="py-1 pr-3 text-right font-normal">{t("col.posts7")}</th>
              <th className="py-1 pr-3 text-right font-normal">{t("col.posts30")}</th>
              <th className="py-1 pr-3 text-right font-normal">{t("col.likes")}</th>
              <th className="py-1 pr-3 text-right font-normal">{t("col.comments")}</th>
              <th className="py-1 text-right font-normal">{t("col.er")}</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((r) => (
              <tr key={(r.username ?? r.entry ?? "") + String(r.mine)} className="border-t border-border">
                <td className="py-1.5 pr-3">
                  {r.username ? `@${r.username}` : r.entry}
                  {r.mine && <span className="ml-1 text-xs text-accent">({t("us")})</span>}
                </td>
                {r.error ? (
                  <td colSpan={6} className="py-1.5 text-xs text-danger">{t("notVisible")}: {r.error}</td>
                ) : (
                  <>
                    <td className="py-1.5 pr-3 text-right">{r.followers?.toLocaleString() ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right">{r.stats?.posts_last_7_days ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right">{r.stats?.posts_last_30_days ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right">{r.stats?.avg_likes ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right">{r.stats?.avg_comments ?? "—"}</td>
                    <td className="py-1.5 text-right">{r.stats?.engagement_rate_percent != null ? `${r.stats.engagement_rate_percent}%` : "—"}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {competitors.some((c) => c.top_posts?.length) && (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-semibold text-muted">{t("topPosts")}</p>
          {competitors.flatMap((c) =>
            (c.top_posts ?? []).slice(0, 2).map((p) => (
              <p key={`${c.username}${p.date}${p.likes}`} className="text-xs" dir="auto">
                @{c.username} · {p.date} · ❤ {p.likes} · 💬 {p.comments} ·{" "}
                {p.permalink ? (
                  <a href={p.permalink} target="_blank" rel="noreferrer" className="text-accent underline">{t("open")}</a>
                ) : null}{" "}
                <span className="text-muted">{p.caption.slice(0, 120)}</span>
              </p>
            )),
          )}
        </div>
      )}
      {own?.recent_customer_comments?.length ? (
        <div className="mt-4 space-y-1">
          <p className="text-xs font-semibold text-muted">{t("customerComments")}</p>
          {own.recent_customer_comments.map((c) => (
            <p key={c.date + c.text} className="text-xs" dir="auto">
              <span className="text-muted">{c.date} · </span>“{c.text}”
            </p>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

export default async function ReportPage({ params }: { params: Promise<{ tenantId: string; reportId: string }> }) {
  const { tenantId, reportId } = await params;
  const me = await requireMe();
  if (!me.memberships.some((m) => m.tenant_id === tenantId)) redirect("/");
  const t = await getTranslations("daily");
  const { data: r, status } = await apiGet<DailyFull>(`/tenants/${tenantId}/daily/${reportId}`);
  if (!r || status === 404) notFound();

  const tm = await getTranslations("meeting");
  const title = r.kind === "market" ? t("marketTitle") : r.kind === "meeting" ? tm("title") : t("briefingTitle");
  return (
    <div className="space-y-6" dir="auto">
      <div>
        <Link href={`/t/${tenantId}/reports`} className="text-sm text-muted hover:text-text">← {t("back")}</Link>
        <PageTitle>{title} · {r.day}</PageTitle>
      </div>
      {r.status === "running" && <Alert>{t("running")}</Alert>}
      {r.status === "failed" && <Alert tone="error">{t("failed")}: {r.error}</Alert>}

      {r.kind === "market" && r.output && (() => {
        const m = r.output as MarketReportData;
        return (
          <>
            <Card>
              <p className="text-lg font-semibold">{m.headline}</p>
              <p className="mt-2 text-sm">{m.summary}</p>
            </Card>
            <div className="grid gap-6 lg:grid-cols-2">
              <Findings title={t("sec.demand")} items={m.demand} />
              <Findings title={t("sec.colors")} items={m.colors_materials} />
              <Findings title={t("sec.competitors")} items={m.competitors} />
              <Findings title={t("sec.customers")} items={m.customer_voice} />
              <Findings title={t("sec.opportunities")} items={m.opportunities} />
              {m.post_ideas.length > 0 && (
                <Card title={t("sec.ideas")}>
                  <ul className="space-y-3 text-sm">
                    {m.post_ideas.map((p) => (
                      <li key={p.product_name + p.angle}>
                        <p className="font-medium">{p.product_name} · <span className="text-muted">{t(`format.${p.format}`)}</span></p>
                        <p>{p.angle}</p>
                        <p className="text-xs text-muted">↳ {p.why}</p>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs text-muted">{t("ideasHint")}</p>
                </Card>
              )}
            </div>
            {(m.questions.length > 0 || m.data_gaps.length > 0) && (
              <Card title={t("sec.gaps")}>
                {m.questions.map((q) => <p key={q} className="text-sm">❓ {q}</p>)}
                {m.data_gaps.map((g) => <p key={g} className="text-xs text-muted">• {g}</p>)}
              </Card>
            )}
          </>
        );
      })()}

      {r.kind === "meeting" && r.output && (() => {
        const m = r.output as MeetingData;
        return (
          <>
            <Card>
              <p className="text-lg font-semibold">{m.focus}</p>
              <p className="mt-2 text-sm">{m.summary}</p>
              <ul className="mt-2 list-inside list-disc text-sm">{m.decisions.map((d) => <li key={d}>{d}</li>)}</ul>
            </Card>
            <Card title={tm("transcript")}>
              <div className="space-y-4 text-sm">
                {m.transcript.map((a) => (
                  <div key={a.agent} className="space-y-1">
                    <p className="text-xs text-muted">→ {a.question}</p>
                    <p><b>{a.agent}</b>: {a.answer}</p>
                    {a.proposals.map((p) => <p key={p.title} className="text-xs">💡 <b>{p.title}</b> — {p.why} ({p.expected_effect})</p>)}
                    {a.risks.map((x) => <p key={x} className="text-xs text-danger">⚠ {x}</p>)}
                    {a.needs_from_owner.map((x) => <p key={x} className="text-xs text-accent">🙋 {x}</p>)}
                  </div>
                ))}
              </div>
            </Card>
            <div className="grid gap-6 lg:grid-cols-2">
              <Card title={tm("weekPlan")}>
                <ul className="space-y-1 text-sm">
                  {m.week_plan.map((s) => <li key={s.date + s.angle}><span className="text-muted">{s.at}</span> · <b>{s.product_name ?? tm("idea")}</b> — {s.angle}</li>)}
                </ul>
              </Card>
              <Card title={tm("improvements")}>
                <ul className="space-y-1 text-sm">
                  {m.improvements.map((i) => <li key={i.title}>{i.owner_action ? "🙋" : "🔧"} <b>{i.title}</b> — <span className="text-muted">{i.why}</span></li>)}
                </ul>
              </Card>
            </div>
          </>
        );
      })()}

      {r.kind === "briefing" && r.output && (() => {
        const b = r.output as BriefingData;
        return (
          <Card>
            <div className="space-y-3 text-sm">
              <p className="font-medium">{b.greeting}</p>
              <p>{b.yesterday}</p>
              {b.market && <p className="rounded-md bg-bg p-3">{b.market}</p>}
              <ol className="list-inside list-decimal">{b.today_plan.map((p) => <li key={p}>{p}</li>)}</ol>
              {b.suggestions.map((s) => (
                <p key={s.title}>
                  <span className="font-medium">{s.title}</span> — <span className="text-muted">{s.why}</span>
                  {s.status === "started" && <span className="ml-2 text-success">✓</span>}
                </p>
              ))}
              {b.questions.map((q) => <p key={q}>❓ {q}</p>)}
            </div>
          </Card>
        );
      })()}

      {r.kind === "market" && <Accounts own={r.input.own} competitors={r.input.competitors ?? []} />}

      {r.sources.length > 0 && (
        <Card title={t("sources")}>
          <ol className="list-inside list-decimal space-y-1 text-sm">
            {r.sources.map((s) => (
              <li key={s.url}>
                <a href={s.url} target="_blank" rel="noreferrer noopener" className="text-accent underline">{s.title}</a>
              </li>
            ))}
          </ol>
        </Card>
      )}
      {r.finished_at && <p className="text-xs text-muted">{t("madeAt", { at: formatDateTime(r.finished_at) })}</p>}
    </div>
  );
}
