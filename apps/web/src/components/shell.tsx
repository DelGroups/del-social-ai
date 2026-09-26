// Frame for signed-in pages: header with company switcher, navigation and account menu.
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import type { ReactNode } from "react";

import type { Me } from "@/lib/types";

import { SignOutButton, TenantSwitcher } from "./client";

export async function Shell({
  me,
  tenantId,
  nav,
  children,
}: {
  me: Me;
  tenantId?: string;
  nav?: { href: string; label: string }[];
  children: ReactNode;
}) {
  const t = await getTranslations();
  return (
    <div className="min-h-screen">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-4 py-3">
          <Link href="/" className="mr-2 text-lg font-semibold">
            DEL SOCIAL <span className="text-accent">AI</span>
          </Link>
          <TenantSwitcher memberships={me.memberships} current={tenantId} />
          <nav className="flex gap-3 text-sm">
            {nav?.map((n) => (
              <Link key={n.href} href={n.href} className="text-muted hover:text-text">
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {me.is_platform_admin && (
              <Link href="/platform" className="text-muted hover:text-text">
                {t("home.platform")}
              </Link>
            )}
            <Link href="/account" className="text-muted hover:text-text">
              {t("common.account")}
            </Link>
            <span className="rounded-md border border-border px-2 py-1 text-xs text-muted">{me.email}</span>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
  );
}

/** Centered single-card layout for sign-in, invitation and reset pages. */
export function AuthFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm space-y-6">
        <p className="text-center text-xl font-semibold">
          DEL SOCIAL <span className="text-accent">AI</span>
        </p>
        <section className="space-y-4 rounded-lg border border-border bg-surface p-6">
          <h1 className="text-lg font-semibold">{title}</h1>
          {children}
        </section>
      </div>
    </main>
  );
}
