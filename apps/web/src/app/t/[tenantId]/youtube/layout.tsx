import { getTranslations } from "next-intl/server";

import { YtTabs } from "@/components/youtube/tabs";

export default async function YoutubeLayout({ children, params }: { children: React.ReactNode; params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const t = await getTranslations("yt");
  const base = `/t/${tenantId}/youtube`;
  return (
    <div className="space-y-5">
      <YtTabs
        tabs={[
          { href: base, label: t("tabs.overview"), exact: true },
          { href: `${base}/videos`, label: t("tabs.videos") },
          { href: `${base}/lab`, label: t("tabs.lab") },
          { href: `${base}/ideas`, label: t("tabs.ideas") },
          { href: `${base}/comments`, label: t("tabs.comments") },
          { href: `${base}/reports`, label: t("tabs.reports") },
          { href: `${base}/settings`, label: t("tabs.settings") },
        ]}
      />
      {children}
    </div>
  );
}
