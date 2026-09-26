"use client";

// One post waiting for a decision: preview, the chosen caption, approve / ask for a change.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { ApiError, api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { PostInfo } from "@/lib/types";

type Props = { tenantId: string; post: PostInfo; canAct: boolean; onChange: () => void };

export function ApprovalCard({ tenantId, post, canAct, onChange }: Props) {
  const t = useTranslations("team");
  const tc = useTranslations("common");
  const [slide, setSlide] = useState(0);
  const [mode, setMode] = useState<"idle" | "confirm" | "change">("idle");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const base = `/tenants/${tenantId}/posts/${post.post_id}`;
  const chosen = post.chosen_option !== null ? post.options[post.chosen_option] : null;
  const photo = post.photos[slide];

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setMode("idle");
      setInstruction("");
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setBusy(false);
    }
  }

  const tone =
    post.status === "ready"
      ? "border-accent"
      : post.status === "published" || post.status === "scheduled"
        ? "border-success"
        : "border-border";

  return (
    <div className={`w-full max-w-2xl space-y-3 rounded-lg border ${tone} bg-surface p-3`}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold">{t(`card.${post.status}`)}</span>
        {post.scheduled_at && <span className="text-muted">· {formatDateTime(post.scheduled_at)}</span>}
        <span className="text-muted">· {post.channels.join(" + ")}</span>
        {chosen && (
          <span className={`rounded-full border px-2 py-0.5 ${chosen.verdict === "pass" ? "border-success text-success" : "border-danger text-danger"}`}>
            {t(`verdict.${chosen.verdict}`)}
          </span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-[200px_1fr]">
        <div className="space-y-1">
          {photo && <img src={photo.url} alt="" className="w-full rounded border border-border" />}
          {post.photos.length > 1 && (
            <div className="flex items-center justify-between text-xs text-muted">
              <button type="button" onClick={() => setSlide((s) => Math.max(0, s - 1))} className="px-2" aria-label="←">←</button>
              <span>{slide + 1} / {post.photos.length}</span>
              <button type="button" onClick={() => setSlide((s) => Math.min(post.photos.length - 1, s + 1))} className="px-2" aria-label="→">→</button>
            </div>
          )}
        </div>
        <div className="min-w-0 space-y-2">
          {post.status === "generating" ? (
            <p className="text-sm text-muted">{t("writing")}</p>
          ) : (
            <pre className={`whitespace-pre-wrap font-sans text-sm leading-relaxed ${expanded ? "" : "line-clamp-6"}`}>{post.caption}</pre>
          )}
          {post.caption && post.caption.length > 300 && (
            <button type="button" className="text-xs text-accent" onClick={() => setExpanded((e) => !e)}>
              {expanded ? t("less") : t("more")}
            </button>
          )}
          {Object.entries(post.results).map(([channel, r]) => (
            <p key={channel} className="text-xs">
              {channel}:{" "}
              {r.url ? (
                <a href={r.url} target="_blank" rel="noreferrer" className="text-accent underline">{t("openPost")}</a>
              ) : (
                <span className="text-danger">{r.error}</span>
              )}
            </p>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      {canAct && post.status === "ready" && mode === "idle" && (
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => setMode("confirm")} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-text">
            {post.scheduled_at ? t("approveAt", { when: formatDateTime(post.scheduled_at) }) : t("approveNow")}
          </button>
          <button type="button" disabled={busy} onClick={() => setMode("change")} className="rounded-md border border-border px-3 py-1.5 text-sm">
            {t("askChange")}
          </button>
          <Link href={`/t/${tenantId}/posts/${post.post_id}`} className="rounded-md px-3 py-1.5 text-sm text-muted hover:text-text">
            {t("details")}
          </Link>
        </div>
      )}
      {mode === "confirm" && (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-bg p-2 text-sm">
          <span>{post.scheduled_at ? t("confirmScheduled") : t("confirmNow", { channels: post.channels.join(" + ") })}</span>
          <button type="button" disabled={busy} onClick={() => run(() => api(`${base}/approve`, { method: "POST", body: { confirm: true } }))} className="rounded-md bg-accent px-3 py-1 font-medium text-accent-text">
            {t("yes")}
          </button>
          <button type="button" onClick={() => setMode("idle")} className="px-2 text-muted">{t("cancel")}</button>
        </div>
      )}
      {mode === "change" && (
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (instruction.trim()) run(() => api(`${base}/revise`, { method: "POST", body: { instruction } }));
          }}
        >
          <input
            autoFocus
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder={t("changePlaceholder")}
            className="min-w-0 flex-1 rounded-md border border-border bg-bg px-3 py-1.5 text-sm"
            maxLength={1000}
          />
          <button type="submit" disabled={busy} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-text">{t("sendChange")}</button>
          <button type="button" onClick={() => setMode("idle")} className="px-2 text-sm text-muted">{t("cancel")}</button>
        </form>
      )}
    </div>
  );
}
