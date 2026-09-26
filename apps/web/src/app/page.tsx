import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Shell } from "@/components/shell";
import { Alert, PageTitle } from "@/components/ui";
import { requireMe } from "@/lib/server-api";

export default async function Home() {
  const me = await requireMe();
  // One company and nothing else to choose: go straight in
  if (me.memberships.length === 1 && !me.is_platform_admin) {
    redirect(`/t/${me.memberships[0].tenant_id}`);
  }
  const t = await getTranslations();
  return (
    <Shell me={me}>
      <PageTitle>{t("home.title")}</PageTitle>
      {me.memberships.length === 0 ? (
        <Alert>{t("home.empty")}</Alert>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {me.memberships.map((m) => (
            <li key={m.tenant_id}>
              <Link
                href={`/t/${m.tenant_id}`}
                className="block rounded-lg border border-border bg-surface p-4 hover:border-accent"
              >
                <span className="block font-medium">{m.tenant_name}</span>
                <span className="text-sm text-muted">{t(`roles.${m.role}`)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}
