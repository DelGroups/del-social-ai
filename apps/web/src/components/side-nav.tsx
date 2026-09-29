"use client";

// Sidebar for company pages: navigation with the current page marked, the package card, the account.
// On phones it collapses into a top bar with a menu button.
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import type { Me, PlanStatus } from "@/lib/types";

import { SignOutButton, TenantSwitcher } from "./client";
import { PrefsSwitcher } from "./prefs-switcher";

export type NavItem = { href: string; label: string; icon: keyof typeof ICONS; badge?: number; exact?: boolean };

const ICONS = {
  home: "M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  team: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6m13 9v-1a4 4 0 0 0-3-3.87M16 4.13a3 3 0 0 1 0 5.74",
  check: "M9 12l2 2 4-4m6 2a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  posts: "M4 5h16v14H4zM4 9h16M9 9v10",
  photos: "M4 5h16v14H4zm4 4.5a1.5 1.5 0 1 0 0-.01M20 15l-5-5L6 19",
  reports: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  youtube: "M3 7.5A3.5 3.5 0 0 1 6.5 4h11A3.5 3.5 0 0 1 21 7.5v9a3.5 3.5 0 0 1-3.5 3.5h-11A3.5 3.5 0 0 1 3 16.5zM10 9v6l5-3z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6m7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14.5 3h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2l.4 2.6h4l.4-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2",
} as const;

function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px] shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

function CreditsCard({ tenantId, plan }: { tenantId: string; plan: PlanStatus | null }) {
  const t = useTranslations("addons");
  const yt = plan?.addons?.find((a) => a.addon_id === "youtube" && a.active);
  if (!yt) return null;
  const pct = yt.monthly_credits ? Math.round((yt.monthly_left / yt.monthly_credits) * 100) : 0;
  return (
    <Link href={`/t/${tenantId}/plan`} className="block space-y-1.5 rounded-lg border border-border bg-bg p-3 text-xs transition hover:border-accent">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">YouTube Studio</span>
        <span className="tabular-nums text-text">{yt.total}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface"><div className="h-full rounded-full bg-[#FF0000]" style={{ width: `${pct}%` }} /></div>
      <p className="text-muted">{t("total")}</p>
    </Link>
  );
}

function PackageCard({ tenantId, plan }: { tenantId: string; plan: PlanStatus | null }) {
  const t = useTranslations("plan");
  if (!plan) return null;
  if (!plan.plan && plan.addons?.some((a) => a.active)) return null; // YouTube-only: the credits card says it all
  const href = `/t/${tenantId}/plan`;
  const posts = plan.posts;
  const pct = posts.limit ? Math.min(100, Math.round((posts.used / posts.limit) * 100)) : 100;
  const bar = plan.state === "ok" ? "bg-success" : plan.state === "warning" ? "bg-accent" : "bg-danger";
  const days = plan.expires_at ? Math.max(0, Math.ceil((Date.parse(plan.expires_at) - Date.now()) / 86_400_000)) : null;
  return (
    <Link href={href} className={`block space-y-2 rounded-lg border bg-bg p-3 text-xs transition hover:border-accent ${plan.state === "ok" ? "border-border" : plan.state === "warning" ? "border-accent" : "border-danger"}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">{plan.plan ? plan.plan.name : t("noPlan")}</span>
        {plan.plan && <span className="text-muted">{t("price", { price: Number(plan.plan.price_azn).toLocaleString() })}</span>}
      </div>
      {plan.plan && (
        <>
          <div>
            <div className="mb-1 flex justify-between text-muted">
              <span>{t("meter.posts")}</span>
              <span className="tabular-nums text-text">{posts.limit === null ? `${posts.used} · ∞` : `${posts.used} / ${posts.limit}`}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface">
              <div className={`h-full rounded-full ${posts.limit === null ? "bg-success/40" : bar}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
          {plan.video.limit !== null && (
            <div className="flex justify-between text-muted">
              <span>{t("meter.video")}</span>
              <span className="tabular-nums text-text">{Math.max(0, plan.video.limit - plan.video.used)} / {plan.video.limit}</span>
            </div>
          )}
          <p className={days !== null && days <= 7 ? "text-accent" : "text-muted"}>
            {days !== null ? t("daysLeft", { days }) : t("noEnd")}
          </p>
        </>
      )}
      <span className="block font-medium text-accent">{t("manage")} →</span>
    </Link>
  );
}

export function SideNav({
  me,
  tenantId,
  items,
  plan,
  prefs,
  children,
}: {
  me: Me;
  tenantId: string;
  items: NavItem[];
  plan: PlanStatus | null;
  prefs: { locale: string; theme: string };
  children: ReactNode;
}) {
  const t = useTranslations();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);
  const active = (i: NavItem) => (i.exact ? path === i.href : path === i.href || path.startsWith(`${i.href}/`));

  const panel = (
    <div className="flex h-full flex-col gap-4 p-4">
      <Link href="/" className="px-2 text-lg font-semibold">
        DEL SOCIAL <span className="text-accent">AI</span>
      </Link>
      <TenantSwitcher memberships={me.memberships} current={tenantId} />
      <nav className="flex flex-col gap-0.5" aria-label={t("tenant.menu")}>
        {items.map((i) => (
          <Link
            key={i.href}
            href={i.href}
            aria-current={active(i) ? "page" : undefined}
            className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
              active(i) ? "bg-accent/12 font-medium text-accent" : "text-muted hover:bg-bg hover:text-text"
            }`}
          >
            <Icon name={i.icon} />
            <span className="flex-1">{i.label}</span>
            {i.badge ? <span className="rounded-full bg-accent px-1.5 text-[11px] font-semibold text-accent-text">{i.badge}</span> : null}
          </Link>
        ))}
      </nav>
      <div className="mt-auto space-y-3">
        <PackageCard tenantId={tenantId} plan={plan} />
        <CreditsCard tenantId={tenantId} plan={plan} />
        <PrefsSwitcher locale={prefs.locale} theme={prefs.theme} />
        <div className="space-y-1 border-t border-border pt-3 text-xs">
          <p className="truncate px-1 text-muted" title={me.email}>{me.email}</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
            <Link href="/account" className="text-muted hover:text-text">{t("common.account")}</Link>
            {me.is_platform_admin && <Link href="/platform" className="text-muted hover:text-text">{t("home.platform")}</Link>}
            <SignOutButton />
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[252px_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-screen overflow-y-auto border-r border-border bg-surface lg:block">{panel}</aside>
      <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-surface px-4 py-3 lg:hidden">
        <button type="button" onClick={() => setOpen(true)} className="rounded-md border border-border px-2 py-1 text-sm" aria-label={t("tenant.menu")}>
          ☰
        </button>
        <Link href="/" className="font-semibold">DEL SOCIAL <span className="text-accent">AI</span></Link>
        {plan?.plan && (
          <Link href={`/t/${tenantId}/plan`} className="ml-auto rounded-full border border-border px-2 py-0.5 text-xs text-muted">
            {plan.plan.name} · {plan.posts.limit === null ? plan.posts.used : `${plan.posts.used}/${plan.posts.limit}`}
          </Link>
        )}
      </header>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <button type="button" className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} aria-label={t("common.close")} />
          <div className="absolute inset-y-0 left-0 w-72 overflow-y-auto bg-surface shadow-xl">{panel}</div>
        </div>
      )}
      <main className="mx-auto w-full max-w-6xl px-4 py-6 lg:px-8">{children}</main>
    </div>
  );
}
