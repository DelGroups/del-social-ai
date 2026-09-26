"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { ApprovalCard } from "@/components/approval-card";
import { api } from "@/lib/client-api";
import type { LiveInfo } from "@/lib/types";

export function ApprovalsInbox({ tenantId, canAct }: { tenantId: string; canAct: boolean }) {
  const t = useTranslations("team");
  const [live, setLive] = useState<LiveInfo | null>(null);
  const refresh = useCallback(async () => {
    try {
      setLive(await api<LiveInfo>(`/tenants/${tenantId}/team/live`));
    } catch {
      /* next poll retries */
    }
  }, [tenantId]);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [refresh]);

  if (!live) return null;
  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold">{t("kpi.waiting")} ({live.waiting.length})</h2>
        {live.waiting.length === 0 ? (
          <p className="text-sm text-muted">{t("nothingWaiting")}</p>
        ) : (
          live.waiting.map((p) => <ApprovalCard key={p.post_id} tenantId={tenantId} post={p} canAct={canAct} onChange={refresh} />)
        )}
      </section>
      {live.scheduled.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold">{t("kpi.scheduled")} ({live.scheduled.length})</h2>
          {live.scheduled.map((p) => <ApprovalCard key={p.post_id} tenantId={tenantId} post={p} canAct={canAct} onChange={refresh} />)}
        </section>
      )}
    </div>
  );
}
