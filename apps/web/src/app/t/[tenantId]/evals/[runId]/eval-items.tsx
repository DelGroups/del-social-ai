"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { EvalItem, EvalOption, EvalRating, EvalRunDetail } from "@/lib/types";

const RATINGS: EvalRating[] = ["publishable", "needs_edit", "wrong"];
const VERDICT_STYLE: Record<string, string> = {
  pass: "border-success text-success",
  fix: "border-accent text-accent",
  block: "border-danger text-danger",
};

type Props = { tenantId: string; run: EvalRunDetail; canRate: boolean };

export function EvalItems({ tenantId, run, canRate }: Props) {
  if (run.suite === "brand_guardian") return <GuardianTable run={run} />;
  return (
    <div className="space-y-6">
      {run.items.map((item) => (
        <ItemCard key={item.item_id} tenantId={tenantId} runId={run.run_id} item={item} canRate={canRate} />
      ))}
    </div>
  );
}

function ItemCard({ tenantId, runId, item, canRate }: { tenantId: string; runId: string; item: EvalItem; canRate: boolean }) {
  const t = useTranslations("evals");
  const tc = useTranslations("common");
  const router = useRouter();
  const [ratings, setRatings] = useState<Record<string, EvalRating>>(item.ratings);
  const [note, setNote] = useState(item.note ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const b = item.brief;
  const options = item.result?.options ?? [];
  const complete = options.length > 0 && options.every((_, i) => ratings[String(i)]);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api(`/tenants/${tenantId}/evals/${runId}/items/${item.item_id}`, {
        method: "PUT",
        body: { ratings, note: note.trim() || null },
      });
      setMessage({ tone: "success", text: t("saved") });
      router.refresh();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof ApiError ? err.message : tc("error") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="mb-4 space-y-1 text-sm">
        <p className="font-semibold">
          {item.position + 1}. {String(b.topic ?? "")}
          {item.rated_at && <span className="ml-2 text-xs text-success">✓ {t("rated")}</span>}
        </p>
        <p className="text-muted">📷 {String(b.photo ?? "")}</p>
        {["goal", "occasion", "product_category", "key_message", "price_text", "notes"].map(
          (k) =>
            b[k] ? (
              <p key={k} className="text-xs text-muted">
                {k}: {String(b[k])}
              </p>
            ) : null,
        )}
        {b.review_hint ? <p className="text-xs text-accent">💡 {String(b.review_hint)}</p> : null}
        {item.result?.question && <Alert>❓ {item.result.question}</Alert>}
        {item.result && (
          <p className="text-xs text-muted">
            {t("revisions", { count: item.result.revisions })} · ${Number(item.result.cost_usd).toFixed(3)}
          </p>
        )}
      </div>

      {item.error && <Alert tone="error">{item.error}</Alert>}

      <div className="grid gap-4 lg:grid-cols-3">
        {options.map((o, i) => (
          <OptionCard
            key={i}
            index={i}
            option={o}
            rating={ratings[String(i)]}
            canRate={canRate}
            onRate={(r) => setRatings((prev) => ({ ...prev, [String(i)]: r }))}
          />
        ))}
      </div>

      {canRate && options.length > 0 && (
        <div className="mt-4 space-y-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("notePlaceholder")}
            rows={2}
            maxLength={2000}
            className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
          />
          <div className="flex items-center gap-3">
            <Button onClick={save} disabled={busy || !complete}>
              {t("save")}
            </Button>
            {!complete && <span className="text-xs text-muted">{t("rateAll")}</span>}
            {message && <Alert tone={message.tone}>{message.text}</Alert>}
          </div>
        </div>
      )}
    </Card>
  );
}

function OptionCard({
  index,
  option,
  rating,
  canRate,
  onRate,
}: {
  index: number;
  option: EvalOption;
  rating: EvalRating | undefined;
  canRate: boolean;
  onRate: (r: EvalRating) => void;
}) {
  const t = useTranslations("evals");
  return (
    <div className="flex flex-col rounded-md border border-border p-3">
      <div className="mb-2 flex items-center gap-2 text-xs">
        <span className="font-semibold">#{index + 1}</span>
        <span className={`rounded-full border px-2 py-0.5 ${VERDICT_STYLE[option.verdict]}`}>
          {t(`verdict.${option.verdict}`)}
        </span>
        <span className="truncate text-muted" title={option.angle}>
          {option.angle}
        </span>
      </div>
      <pre className="mb-3 flex-1 whitespace-pre-wrap font-sans text-sm leading-relaxed">{option.caption}</pre>
      {option.findings.length > 0 && (
        <details className="mb-3 text-xs">
          <summary className="cursor-pointer text-muted">{t("findings", { count: option.findings.length })}</summary>
          <ul className="mt-2 space-y-1">
            {option.findings.map((f, i) => (
              <li key={i} className={f.severity === "block" ? "text-danger" : "text-muted"}>
                [{f.source}/{f.code}] {f.message}
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="flex flex-wrap gap-1">
        {RATINGS.map((r) => (
          <button
            key={r}
            type="button"
            disabled={!canRate}
            onClick={() => onRate(r)}
            className={`rounded-md border px-2 py-1 text-xs transition disabled:cursor-default ${
              rating === r
                ? r === "publishable"
                  ? "border-success bg-success/10 text-success"
                  : r === "wrong"
                    ? "border-danger bg-danger/10 text-danger"
                    : "border-accent bg-accent/10 text-accent"
                : "border-border text-muted hover:text-text"
            }`}
          >
            {t(`rating.${r}`)}
          </button>
        ))}
      </div>
    </div>
  );
}

function GuardianTable({ run }: { run: EvalRunDetail }) {
  const t = useTranslations("evals");
  return (
    <Card>
      <table className="w-full text-left text-sm">
        <thead className="text-muted">
          <tr>
            <th className="py-2 pr-4 font-medium">{t("case")}</th>
            <th className="py-2 pr-4 font-medium">{t("expected")}</th>
            <th className="py-2 pr-4 font-medium">{t("got")}</th>
            <th className="py-2 font-medium">{t("findingsCol")}</th>
          </tr>
        </thead>
        <tbody>
          {run.items.map((item) => {
            const r = item.result as unknown as {
              expect: string;
              got: string;
              correct: boolean;
              findings: EvalOption["findings"];
            } | null;
            return (
              <tr key={item.item_id} className="border-t border-border align-top">
                <td className="py-2 pr-4">{String(item.brief.id)}</td>
                <td className="py-2 pr-4">{r?.expect ?? String(item.brief.expect)}</td>
                <td className={`py-2 pr-4 font-semibold ${r?.correct ? "text-success" : "text-danger"}`}>
                  {r ? `${r.got} ${r.correct ? "✓" : "✗"}` : item.error ?? "…"}
                </td>
                <td className="py-2 text-xs text-muted">
                  {r?.findings.map((f, i) => (
                    <div key={i}>
                      [{f.source}/{f.code}] {f.message}
                    </div>
                  ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
