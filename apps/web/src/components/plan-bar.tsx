// The company's package on every page: posts left this month, expiry, and a warning when work is paused.
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { formatDate } from "@/lib/prefs";
import type { PlanStatus } from "@/lib/types";

const daysLeft = (iso: string) => Math.max(0, Math.ceil((Date.parse(iso) - Date.now()) / 86_400_000));

export async function PlanBar({ tenantId, plan }: { tenantId: string; plan: PlanStatus | null }) {
  if (!plan || plan.state === "ok") return null; // the sidebar card shows the package; this bar only warns
  const t = await getTranslations("plan");
  const href = `/t/${tenantId}/plan`;
  const { posts } = plan;
  const pct = posts.limit ? Math.min(100, Math.round((posts.used / posts.limit) * 100)) : 0;
  const tone = plan.state === "warning" ? "border-accent" : "border-danger";

  let message: string | null = null;
  if (plan.state === "none") message = t("banner.none");
  else if (plan.state === "expired" && plan.expires_at) message = t("banner.expired", { date: formatDate(plan.expires_at) });
  else if (plan.state === "limit" && plan.period_end)
    message = t("banner.limit", { used: posts.used, limit: posts.limit ?? 0, date: formatDate(plan.period_end) });
  else if (plan.state === "warning") {
    const soon = plan.expires_at && daysLeft(plan.expires_at) <= 7;
    message = soon
      ? t("banner.endsSoon", { date: formatDate(plan.expires_at!), days: daysLeft(plan.expires_at!) })
      : t("banner.fewLeft", { left: Math.max(0, (posts.limit ?? 0) - posts.used) });
  }

  return (
    <div className={`mb-6 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border ${tone} bg-surface px-4 py-2.5 text-sm`}>
      {plan.plan ? (
        <Link href={href} className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1 hover:text-accent">
          <span className="font-semibold">{t("badge", { plan: plan.plan.name })}</span>
          <span className="flex items-center gap-2 text-muted">
            {posts.limit === null ? (
              t("postsUnlimited", { used: posts.used })
            ) : (
              <>
                <span className="h-1.5 w-24 overflow-hidden rounded-full bg-bg" aria-hidden="true">
                  <span
                    className={`block h-full rounded-full ${plan.state === "warning" ? "bg-accent" : "bg-danger"}`}
                    style={{ width: `${pct}%` }}
                  />
                </span>
                {t("postsOf", { used: posts.used, limit: posts.limit })}
              </>
            )}
          </span>
          {plan.video.limit !== null && (
            <span className="text-muted">{t("videoOf", { left: Math.max(0, plan.video.limit - plan.video.used), limit: plan.video.limit })}</span>
          )}
          <span className="text-muted">
            {plan.expires_at ? t("until", { date: formatDate(plan.expires_at), days: daysLeft(plan.expires_at) }) : t("noEnd")}
          </span>
        </Link>
      ) : (
        <span className="flex-1 font-semibold">{t("noPlan")}</span>
      )}
      {message && <span className={plan.state === "warning" ? "text-accent" : "text-danger"}>{message}</span>}
      <Link href={href} className="rounded-md border border-border px-2.5 py-1 text-xs hover:border-accent">
        {t("upgrade")}
      </Link>
    </div>
  );
}
