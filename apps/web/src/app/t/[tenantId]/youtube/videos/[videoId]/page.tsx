import { redirect } from "next/navigation";

import { VideoStudio } from "@/components/youtube/video-studio";
import { requireMe } from "@/lib/server-api";
import { canApprove } from "@/lib/types";

export default async function Page({ params }: { params: Promise<{ tenantId: string; videoId: string }> }) {
  const { tenantId, videoId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  return <VideoStudio tenantId={tenantId} videoId={videoId} canWork={canApprove(membership.role)} />;
}
