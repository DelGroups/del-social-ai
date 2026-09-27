"use client";

// The result of a team meeting in the Team Room: who said what, what the Team Lead decided, goals
// to accept, the week plan to approve with one click, what must improve, questions.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { AGENT_COLOR } from "@/lib/agents";
import { ApiError, api } from "@/lib/client-api";
import type { GoalInfo, MeetingData } from "@/lib/types";

const fmt = (v: number | null, unit: string) => (v === null ? "—" : `${Number.isInteger(v) ? v : v.toFixed(2)}${unit === "%" ? "%" : ""}`);

export function GoalRow({ tenantId, goal, canDecide, onChange }: { tenantId: string; goal: GoalInfo; canDecide: boolean; onChange: () => void }) {
  const t = useTranslations("goals");
  const tc = useTranslations("common");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(accept: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api(`/tenants/${tenantId}/goals/${goal.goal_id}/decision`, { method: "POST", body: { accept } });
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setBusy(false);
    }
  }

  const tone = goal.status === "achieved" ? "text-success" : goal.status === "missed" ? "text-danger" : goal.status === "proposed" ? "text-accent" : "text-muted";
  return (
    <div className="space-y-1.5 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">🎯 {goal.title}</span>
        <span className={`rounded-full border border-current px-2 py-0.5 text-[11px] ${tone}`}>{t(`status.${goal.status}`)}</span>
        <span className="ml-auto text-xs text-muted">{t("due", { date: goal.due })}</span>
      </div>
      <div className="flex items-center gap-2 text-xs">
        <span className="tabular-nums text-muted">{t(`metric.${goal.metric}`)}: {fmt(goal.current, goal.unit)} → {fmt(goal.target, goal.unit)}</span>
        {goal.progress !== null && goal.status !== "proposed" && (
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg">
            <span className={`block h-full rounded-full ${goal.status === "achieved" ? "bg-success" : "bg-accent"}`} style={{ width: `${goal.progress}%` }} />
          </span>
        )}
      </div>
      <p className="text-xs text-muted">{goal.why}</p>
      {goal.status === "proposed" && canDecide && (
        <div className="flex gap-2 pt-1">
          <button type="button" disabled={busy} onClick={() => decide(true)} className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-accent-text disabled:opacity-50">{t("accept")}</button>
          <button type="button" disabled={busy} onClick={() => decide(false)} className="rounded-md border border-border px-3 py-1 text-xs disabled:opacity-50">{t("decline")}</button>
        </div>
      )}
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}

export function MeetingCard({
  tenantId,
  messageId,
  data,
  reportId,
  canAct,
  onChange,
}: {
  tenantId: string;
  messageId: string;
  data: MeetingData;
  reportId: string;
  canAct: boolean;
  onChange: () => void;
}) {
  const t = useTranslations("meeting");
  const ta = useTranslations("team");
  const tc = useTranslations("common");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const openSlots = data.week_plan.filter((s) => s.status === "open").length;

  async function acceptPlan() {
    if (!confirm(t("planConfirm", { count: openSlots }))) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await api<{ started: number; stopped: string | null }>(`/tenants/${tenantId}/team/messages/${messageId}/plan/accept`, { method: "POST" });
      setNote({ ok: true, text: t("planStarted", { count: r.started }) + (r.stopped ? ` ${r.stopped}` : "") });
      onChange();
    } catch (err) {
      setNote({ ok: false, text: err instanceof ApiError ? err.message : tc("error") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-2xl space-y-4 rounded-lg border border-accent/60 bg-surface p-4 text-sm" dir="auto">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-accent">{t("title")}</p>
        <p className="mt-1 font-medium">{data.focus}</p>
      </div>

      <div className="space-y-2">
        <button type="button" onClick={() => setOpen((o) => !o)} className="text-xs font-semibold text-muted hover:text-text">
          {open ? "▾" : "▸"} {t("transcript")}
        </button>
        {open &&
          data.transcript.map((a) => (
            <div key={a.agent} className="space-y-1 border-l-2 pl-3" style={{ borderColor: AGENT_COLOR[a.agent] }}>
              <p className="text-xs text-muted">
                <b className="text-text">{ta("agents.team_lead")}</b> → {ta(`agents.${a.agent}`)}: {a.question}
              </p>
              <p><b>{ta(`agents.${a.agent}`)}:</b> {a.answer}</p>
              {a.proposals.map((p) => (
                <p key={p.title} className="text-xs">💡 <b>{p.title}</b> — {p.why} <span className="text-muted">({p.expected_effect})</span></p>
              ))}
              {a.risks.map((r) => <p key={r} className="text-xs text-danger">⚠ {r}</p>)}
            </div>
          ))}
      </div>

      <div className="rounded-md bg-bg p-3">
        <p className="mb-1 text-xs font-semibold text-muted">{t("decision")}</p>
        <p>{data.summary}</p>
        <ul className="mt-2 list-inside list-disc space-y-0.5">
          {data.decisions.map((d) => <li key={d}>{d}</li>)}
        </ul>
      </div>

      {(data.goals ?? []).length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted">{t("goals")}</p>
          {data.goals!.map((g) => <GoalRow key={g.goal_id} tenantId={tenantId} goal={g} canDecide={canAct} onChange={onChange} />)}
        </div>
      )}

      {data.week_plan.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted">{t("weekPlan")}</p>
          <ul className="space-y-1.5">
            {data.week_plan.map((s) => (
              <li key={s.date + s.angle} className="rounded-md border border-border px-3 py-2">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="tabular-nums text-muted">{s.at} · {t(`format.${s.format}`)}</span>
                  {s.status === "started" && s.post_id ? (
                    <Link href={`/t/${tenantId}/posts/${s.post_id}`} className="text-success">✓ {t("prepared")}</Link>
                  ) : (
                    <span className={s.status === "open" ? "text-accent" : "text-muted"}>{t(`slot.${s.status}`)}</span>
                  )}
                </div>
                <p className="mt-0.5">
                  <b>{s.product_name ?? t("idea")}</b> — {s.angle}
                </p>
              </li>
            ))}
          </ul>
          {canAct && openSlots > 0 && (
            <button type="button" disabled={busy} onClick={acceptPlan} className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-text disabled:opacity-50">
              {busy ? "…" : t("acceptPlan", { count: openSlots })}
            </button>
          )}
          {note && <p className={`text-xs ${note.ok ? "text-success" : "text-danger"}`}>{note.text}</p>}
        </div>
      )}

      {data.improvements.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-muted">{t("improvements")}</p>
          {data.improvements.map((i) => (
            <p key={i.title}>
              {i.owner_action ? "🙋 " : "🔧 "}
              <b>{i.title}</b> <span className="text-muted">— {i.why}</span>
              {i.owner_action && <span className="ml-1 rounded bg-accent/15 px-1 text-[11px] text-accent">{t("needsYou")}</span>}
            </p>
          ))}
        </div>
      )}

      {data.questions.length > 0 && (
        <div className="rounded-md bg-accent/10 p-3">
          {data.questions.map((q) => <p key={q}>❓ {q}</p>)}
          <p className="mt-1 text-xs text-muted">{t("answerInChat")}</p>
        </div>
      )}
      <Link href={`/t/${tenantId}/reports/${reportId}`} className="inline-block text-xs text-muted underline">{t("full")}</Link>
    </div>
  );
}
