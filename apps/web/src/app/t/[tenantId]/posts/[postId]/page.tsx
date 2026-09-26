import { getTranslations } from "next-intl/server";
import { notFound, redirect } from "next/navigation";

import { PageTitle } from "@/components/ui";
import { apiGet, requireMe } from "@/lib/server-api";
import { type MediaAsset, type PostInfo, canApprove } from "@/lib/types";

import { PostEditor } from "./post-editor";

export default async function PostPage({ params }: { params: Promise<{ tenantId: string; postId: string }> }) {
  const { tenantId, postId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const [{ data: post }, t] = await Promise.all([apiGet<PostInfo>(`/tenants/${tenantId}/posts/${postId}`), getTranslations("posts")]);
  if (!post) notFound();
  // The product's other publishable photos can be added to the post
  const { data: productPhotos } = post.product_id
    ? await apiGet<MediaAsset[]>(`/tenants/${tenantId}/media?product_id=${post.product_id}`)
    : { data: [] as MediaAsset[] };
  return (
    <>
      <PageTitle>{t("postTitle")}</PageTitle>
      <PostEditor
        tenantId={tenantId}
        post={post}
        productPhotos={(productPhotos ?? []).filter((m) => m.publishable)}
        canApprove={canApprove(membership.role)}
      />
    </>
  );
}
