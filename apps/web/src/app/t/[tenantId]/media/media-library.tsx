"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Alert, Button, Card, Field, Input, Select } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { MediaAsset } from "@/lib/types";

// Photos larger than this are scaled down in the browser before upload: posts are
// published at 1080 px, and smaller uploads pass the panel's proxy quickly.
const MAX_SIDE = 3200;
const RESIZABLE = ["image/jpeg", "image/png", "image/webp"];

async function shrinkIfLarge(file: File): Promise<File> {
  if (!RESIZABLE.includes(file.type)) return file; // e.g. HEIC: sent as is, the server converts it
  const bitmap = await createImageBitmap(file).catch(() => null);
  if (!bitmap || Math.max(bitmap.width, bitmap.height) <= MAX_SIDE) return file;
  const scale = MAX_SIDE / Math.max(bitmap.width, bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  return blob ? new File([blob], file.name.replace(/\.\w+$/, ".jpg"), { type: "image/jpeg" }) : file;
}

async function uploadFile(tenantId: string, file: File, kind: string, description: string, tags: string) {
  const form = new FormData();
  form.append("file", kind === "logo" ? file : await shrinkIfLarge(file));
  form.append("kind", kind);
  form.append("description", description);
  form.append("tags", tags);
  const res = await fetch(`/api/tenants/${tenantId}/media`, { method: "POST", body: form, credentials: "same-origin" });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, typeof data?.detail === "string" ? data.detail : res.statusText);
}

type Props = { tenantId: string; assets: MediaAsset[]; canManage: boolean };

export function MediaLibrary({ tenantId, assets, canManage }: Props) {
  const t = useTranslations("media");
  const tc = useTranslations("common");
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const logo = assets.find((a) => a.kind === "logo");
  const photos = assets.filter((a) => a.kind === "photo");
  const allTags = [...new Set(photos.flatMap((p) => p.tags))].sort();
  const shown = filter ? photos.filter((p) => p.tags.includes(filter)) : photos;
  const current = assets.find((a) => a.asset_id === selected) ?? null;

  async function onUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    const files = Array.from(fileRef.current?.files ?? []);
    if (files.length === 0) return;
    setBusy(true);
    setError(null);
    const failed: string[] = [];
    for (const [i, file] of files.entries()) {
      setProgress(t("uploading", { current: i + 1, total: files.length }));
      try {
        await uploadFile(tenantId, file, String(form.get("kind")), String(form.get("description") ?? ""), String(form.get("tags") ?? ""));
      } catch (err) {
        failed.push(`${file.name}: ${err instanceof ApiError ? err.message : tc("error")}`);
      }
    }
    setProgress(null);
    setBusy(false);
    if (failed.length) setError(failed.join(" · "));
    else formEl.reset();
    router.refresh();
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">{t("intro")}</p>
      {error && <Alert tone="error">{error}</Alert>}

      {canManage && (
        <Card title={t("uploadTitle")}>
          <form onSubmit={onUpload} className="grid gap-4 md:grid-cols-2">
            <Field label={t("files")} hint={t("filesHint")}>
              <input
                ref={fileRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
                multiple
                required
                className="block w-full text-sm text-muted file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-2 file:text-text"
              />
            </Field>
            <Field label={t("kind")}>
              <Select name="kind" defaultValue="photo" className="w-full">
                <option value="photo">{t("kindPhoto")}</option>
                <option value="logo">{t("kindLogo")}</option>
              </Select>
            </Field>
            <Field label={t("description")} hint={t("descriptionHint")}>
              <Input name="description" maxLength={500} />
            </Field>
            <Field label={t("tags")} hint={t("tagsHint")}>
              <Input name="tags" maxLength={1000} />
            </Field>
            <div className="flex items-center gap-3 md:col-span-2">
              <Button type="submit" disabled={busy}>
                {t("upload")}
              </Button>
              {progress && <span className="text-sm text-muted">{progress}</span>}
            </div>
          </form>
        </Card>
      )}

      <Card title={t("logoTitle")}>
        {logo ? (
          <div className="flex items-center gap-4">
            <img src={logo.urls.thumb} alt={t("kindLogo")} className="h-20 w-auto rounded border border-border bg-white p-2" />
            <p className="text-sm text-muted">{t("logoHint")}</p>
          </div>
        ) : (
          <p className="text-sm text-muted">{t("noLogo")}</p>
        )}
      </Card>

      <Card title={t("photosTitle", { count: photos.length })}>
        {allTags.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-2 text-xs">
            <TagChip active={!filter} onClick={() => setFilter("")} label={t("allTags")} />
            {allTags.map((tag) => (
              <TagChip key={tag} active={filter === tag} onClick={() => setFilter(tag)} label={tag} />
            ))}
          </div>
        )}
        {shown.length === 0 ? (
          <p className="text-sm text-muted">{t("empty")}</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {shown.map((a) => (
              <button
                key={a.asset_id}
                type="button"
                onClick={() => setSelected(a.asset_id)}
                className={`overflow-hidden rounded-md border text-left transition ${selected === a.asset_id ? "border-accent" : "border-border hover:border-accent"}`}
              >
                <img src={a.urls.thumb} alt={a.description || a.filename} className="aspect-square w-full object-cover" loading="lazy" />
                <div className="space-y-1 p-2 text-xs">
                  <p className="line-clamp-2">{a.description || <span className="text-muted">{t("noDescription")}</span>}</p>
                  <p className="truncate text-muted">{a.tags.join(" · ")}</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>

      {current && (
        <PhotoEditor
          key={current.asset_id + current.focal_x + current.focal_y + current.enhance}
          tenantId={tenantId}
          asset={current}
          hasLogo={Boolean(logo)}
          canManage={canManage}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

function TagChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 ${active ? "border-accent text-accent" : "border-border text-muted hover:text-text"}`}
    >
      {label}
    </button>
  );
}

function PhotoEditor({
  tenantId,
  asset,
  hasLogo,
  canManage,
  onClose,
}: {
  tenantId: string;
  asset: MediaAsset;
  hasLogo: boolean;
  canManage: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("media");
  const tc = useTranslations("common");
  const router = useRouter();
  const [description, setDescription] = useState(asset.description);
  const [tags, setTags] = useState(asset.tags.join(", "));
  const [focal, setFocal] = useState({ x: asset.focal_x, y: asset.focal_y });
  const [enhance, setEnhance] = useState(asset.enhance);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [preview, setPreview] = useState<"feed" | "square">("feed");

  async function run(action: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      if (done) setMessage({ tone: "success", text: done });
      router.refresh();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof ApiError ? err.message : tc("error") });
    } finally {
      setBusy(false);
    }
  }

  function pickFocal(e: React.MouseEvent<HTMLImageElement>) {
    if (!canManage) return;
    const r = e.currentTarget.getBoundingClientRect();
    setFocal({
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    });
  }

  const previewUrl = asset.urls[hasLogo ? `${preview}-logo` : preview] ?? asset.urls[preview];

  return (
    <Card title={asset.filename}>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-2">
          <p className="text-xs text-muted">{canManage ? t("focalHint") : t("original")}</p>
          <div className="relative inline-block">
            <img src={asset.urls.thumb} alt="" onClick={pickFocal} className={`max-h-80 w-auto rounded ${canManage ? "cursor-crosshair" : ""}`} />
            <span
              className="pointer-events-none absolute h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow"
              style={{ left: `${focal.x * 100}%`, top: `${focal.y * 100}%`, background: "rgba(255,122,26,.6)" }}
            />
          </div>
          <p className="text-xs text-muted">
            {asset.width}×{asset.height} · {(asset.bytes / 1024 / 1024).toFixed(1)} MB
          </p>
        </div>
        <div className="space-y-2">
          <div className="flex gap-2 text-xs">
            <TagChip active={preview === "feed"} onClick={() => setPreview("feed")} label={t("previewFeed")} />
            <TagChip active={preview === "square"} onClick={() => setPreview("square")} label={t("previewSquare")} />
          </div>
          <img src={previewUrl} alt={t("previewAlt")} className="max-h-96 w-auto rounded border border-border" />
          <p className="text-xs text-muted">{t("previewHint")}</p>
        </div>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Field label={t("description")} hint={t("descriptionHint")}>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} disabled={!canManage} maxLength={500} />
        </Field>
        <Field label={t("tags")} hint={t("tagsHint")}>
          <Input value={tags} onChange={(e) => setTags(e.target.value)} disabled={!canManage} />
        </Field>
        <label className="flex items-center gap-2 text-sm md:col-span-2">
          <input type="checkbox" checked={enhance} onChange={(e) => setEnhance(e.target.checked)} disabled={!canManage} />
          {t("enhance")}
        </label>
      </div>

      {message && (
        <div className="mt-4">
          <Alert tone={message.tone}>{message.text}</Alert>
        </div>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        {canManage && (
          <Button
            disabled={busy}
            onClick={() =>
              run(
                () =>
                  api(`/tenants/${tenantId}/media/${asset.asset_id}`, {
                    method: "PATCH",
                    body: {
                      description,
                      tags: tags.split(",").map((s) => s.trim()).filter(Boolean),
                      focal_x: focal.x,
                      focal_y: focal.y,
                      enhance,
                    },
                  }),
                t("saved"),
              )
            }
          >
            {t("save")}
          </Button>
        )}
        <Button variant="ghost" onClick={onClose}>
          {t("close")}
        </Button>
        {canManage && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() =>
              confirm(t("deleteConfirm")) &&
              run(async () => {
                await api(`/tenants/${tenantId}/media/${asset.asset_id}`, { method: "DELETE" });
                onClose();
              })
            }
          >
            {t("delete")}
          </Button>
        )}
      </div>
    </Card>
  );
}
