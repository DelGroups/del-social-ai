import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Card, PageTitle } from "@/components/ui";
import { formatDateTime } from "@/lib/prefs";
import { apiGet, requireMe } from "@/lib/server-api";
import { type PostInfo, type ProductInfo, canApprove } from "@/lib/types";

import { NewPostForm } from "./new-post-form";
import { StatusBadge } from "./status-badge";

export default async function PostsPage({ params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const me = await requireMe();
  const membership = me.memberships.find((m) => m.tenant_id === tenantId);
  if (!membership) redirect("/");
  const [{ data: posts }, { data: products }, t] = await Promise.all([
    apiGet<PostInfo[]>(`/tenants/${tenantId}/posts`),
    apiGet<ProductInfo[]>(`/tenants/${tenantId}/products`),
    getTranslations("posts"),
  ]);
  return (
    <>
      <PageTitle>{t("title")}</PageTitle>
      {canApprove(membership.role) && <NewPostForm tenantId={tenantId} products={products ?? []} />}
      <div className="mt-6 space-y-3">
        {(posts ?? []).length === 0 && <p className="text-sm text-muted">{t("empty")}</p>}
        {(posts ?? []).map((p) => (
          <Link key={p.post_id} href={`/t/${tenantId}/posts/${p.post_id}`} className="block">
            <Card className="transition hover:border-accent">
              <div className="flex items-center gap-4">
                {p.photos[0] && <img src={p.photos[0].url} alt="" className="h-16 w-16 rounded object-cover" />}
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <StatusBadge status={p.status} />
                    <span className="text-muted">
                      {t("photoCount", { count: p.photos.length })} · {p.channels.join(" + ")} · {formatDateTime(p.created_at)}
                    </span>
                  </div>
                  <p className="line-clamp-2 text-sm">{p.caption ?? t("writing")}</p>
                </div>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </>
  );
}
