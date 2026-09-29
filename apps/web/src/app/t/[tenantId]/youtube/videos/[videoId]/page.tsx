import { redirect } from "next/navigation";

import { VideoStudio } from "@/components/youtube/video-studio";
import { requireMe } from "@/lib/server-api";
import { canApprove } from "@/lib/types";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ tenantId: string; videoId: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tenantId, videoId } = await params;
  const { tab } = await searchParams;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  return <VideoStudio tenantId={tenantId} videoId={videoId} canWork={canApprove(membership.role)} initialTab={tab === "kit" ? "kit" : "thumbs"} />;
}
