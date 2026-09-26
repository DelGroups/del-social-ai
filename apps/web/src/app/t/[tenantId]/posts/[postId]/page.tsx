import { getTranslations } from "next-intl/server";
import { notFound, redirect } from "next/navigation";

import { PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type PostInfo, canApprove } from "@/lib/types";

import { PostEditor } from "./post-editor";

export default async function PostPage({ params }: { params: Promise<{ tenantId: string; postId: string }> }) {
  const { tenantId, postId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const [{ data: post }, t] = await Promise.all([apiGet<PostInfo>(`/tenants/${tenantId}/posts/${postId}`), getTranslations("posts")]);
  if (!post) notFound();
  return (
    <>
      <PageTitle>{t("postTitle")}</PageTitle>
      <PostEditor tenantId={tenantId} post={post} canApprove={canApprove(membership.role)} />
    </>
  );
}
