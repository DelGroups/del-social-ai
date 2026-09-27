"use client";

// Buttons to make today's market research or morning report now (they cost AI credit).
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError, api } from "@/lib/client-api";

export function DailyActions({ tenantId }: { tenantId: string }) {
  const t = useTranslations("daily");
  const tc = useTranslations("common");
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  async function run(kind: "market" | "briefing") {
    if (!confirm(t(`confirm.${kind}`))) return;
    setBusy(kind);
    setNote(null);
    try {
      await api(`/tenants/${tenantId}/daily/${kind}/run`, { method: "POST" });
      setNote({ tone: "ok", text: t(`started.${kind}`) });
      router.refresh();
    } catch (err) {
      setNote({ tone: "error", text: err instanceof ApiError ? err.message : tc("error") });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {(["market", "briefing"] as const).map((k) => (
        <button
          key={k}
          type="button"
          disabled={busy !== null}
          onClick={() => run(k)}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:border-accent disabled:opacity-50"
        >
          {busy === k ? "…" : t(`run.${k}`)}
        </button>
      ))}
      {note && <span className={`text-sm ${note.tone === "ok" ? "text-success" : "text-danger"}`}>{note.text}</span>}
    </div>
  );
}
