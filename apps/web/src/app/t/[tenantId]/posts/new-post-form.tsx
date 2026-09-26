"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Card, Field, Select } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { PostInfo, ProductInfo } from "@/lib/types";

export function NewPostForm({ tenantId, products }: { tenantId: string; products: ProductInfo[] }) {
  const t = useTranslations("posts");
  const tc = useTranslations("common");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const channels = ["instagram", "facebook"].filter((c) => f.get(c) === "on");
    setBusy(true);
    setError(null);
    try {
      const post = await api<PostInfo>(`/tenants/${tenantId}/posts`, {
        method: "POST",
        body: {
          product_id: f.get("product_id"),
          format: f.get("format") || null,
          with_logo: f.get("with_logo") === "on",
          channels,
          notes: f.get("notes") ?? "",
        },
      });
      router.push(`/t/${tenantId}/posts/${post.post_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
      setBusy(false);
    }
  }

  if (products.length === 0) return <Alert>{t("noProducts")}</Alert>;

  return (
    <Card title={t("newTitle")}>
      <form onSubmit={onSubmit} className="grid gap-4 md:grid-cols-2">
        <Field label={t("product")} hint={t("productHint")}>
          <Select name="product_id" required className="w-full">
            {products.map((p) => (
              <option key={p.product_id} value={p.product_id}>
                {p.name} ({p.photos})
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("format")}>
          <Select name="format" defaultValue="" className="w-full">
            <option value="">{t("formatAuto")}</option>
            <option value="feed">Instagram 4:5</option>
            <option value="square">1:1</option>
            <option value="landscape">1.91:1</option>
          </Select>
        </Field>
        <div className="flex flex-wrap items-center gap-4 text-sm md:col-span-2">
          <label className="flex items-center gap-2">
            <input type="checkbox" name="instagram" defaultChecked /> Instagram
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" name="facebook" defaultChecked /> Facebook
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" name="with_logo" defaultChecked /> {t("withLogo")}
          </label>
        </div>
        <div className="md:col-span-2">
          <Field label={t("notes")} hint={t("notesHint")}>
            <textarea
              name="notes"
              rows={2}
              maxLength={1000}
              className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
            />
          </Field>
        </div>
        <div className="flex items-center gap-3 md:col-span-2">
          <Button type="submit" disabled={busy}>
            {t("create")}
          </Button>
          <span className="text-xs text-muted">{t("createHint")}</span>
        </div>
        {error && (
          <div className="md:col-span-2">
            <Alert tone="error">{error}</Alert>
          </div>
        )}
      </form>
    </Card>
  );
}
