"use client";

// YouTube Studio's own menu: a row of tabs under the page header (scrolls sideways on phones).
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BrandLogo } from "@/lib/brand-icons";

export function YtTabs({ tabs }: { tabs: { href: string; label: string; exact?: boolean }[] }) {
  const path = usePathname();
  const active = (t: { href: string; exact?: boolean }) => (t.exact ? path === t.href : path === t.href || path.startsWith(`${t.href}/`));
  return (
    <div className="flex items-center gap-3 border-b border-border">
      <span className="hidden shrink-0 items-center gap-2 pb-2 text-sm font-semibold sm:flex">
        <BrandLogo channel="youtube" size={20} /> Studio
      </span>
      <nav className="-mb-px flex min-w-0 flex-1 gap-1 overflow-x-auto" aria-label="YouTube Studio">
        {tabs.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active(t) ? "page" : undefined}
            className={`shrink-0 border-b-2 px-3 py-2 text-sm transition ${
              active(t) ? "border-[#FF0000] font-medium text-text" : "border-transparent text-muted hover:text-text"
            }`}
          >
            {t.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
