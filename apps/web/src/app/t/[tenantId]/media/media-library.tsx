"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Alert, Button, Card, Field, Input, Select } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { MediaAsset, MediaSource, PhotoAnalysis, ProductInfo, Recipe, RecipeStep } from "@/lib/types";

// Photos larger than this are scaled down in the browser before upload: posts are
// published at 1080 px, and smaller uploads pass the panel's proxy quickly.
const MAX_SIDE = 3200;
const RESIZABLE = ["image/jpeg", "image/png", "image/webp"];
const SOURCES: MediaSource[] = ["own", "render", "licensed", "reference"];
const EMPTY_STEP: RecipeStep = { on: false, request: "", reference_asset_id: null };
const EMPTY_RECIPE: Recipe = {
  subject: "",
  enhance: false,
  remove: EMPTY_STEP,
  background: EMPTY_STEP,
  recolor: EMPTY_STEP,
  swap: EMPTY_STEP,
};

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

async function uploadFile(tenantId: string, file: File, fields: Record<string, string>) {
  const form = new FormData();
  form.append("file", fields.kind === "logo" ? file : await shrinkIfLarge(file));
  for (const [k, v] of Object.entries(fields)) form.append(k, v);
  const res = await fetch(`/api/tenants/${tenantId}/media`, { method: "POST", body: form, credentials: "same-origin" });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, typeof data?.detail === "string" ? data.detail : res.statusText);
}

type Props = { tenantId: string; assets: MediaAsset[]; products: ProductInfo[]; canManage: boolean };
type Format = "feed" | "square" | "landscape";

export function MediaLibrary({ tenantId, assets, products, canManage }: Props) {
  const t = useTranslations("media");
  const tc = useTranslations("common");
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [productFilter, setProductFilter] = useState("");

  const logos = assets.filter((a) => a.kind === "logo");
  const logo = logos.find((a) => a.default_logo) ?? logos[0]; // same rule as the API
  const photos = assets.filter((a) => a.kind === "photo");
  const allTags = [...new Set(photos.flatMap((p) => p.tags))].sort();
  const byProduct = productFilter ? photos.filter((p) => p.product_id === productFilter).sort((a, b) => a.position - b.position) : photos;
  const shown = filter ? byProduct.filter((p) => p.tags.includes(filter)) : byProduct;
  const activeProduct = products.find((p) => p.product_id === productFilter) ?? null;
  const current = assets.find((a) => a.asset_id === selected) ?? null;
  const pending = assets.some(
    (a) => a.status === "pending" || a.analysis?.status === "queued" || a.analysis?.status === "running",
  );

  // AI edits finish in the background: refresh until none is pending
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => router.refresh(), 4000);
    return () => clearInterval(timer);
  }, [pending, router]);

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
        await uploadFile(tenantId, file, {
          kind: String(form.get("kind")),
          source: String(form.get("source")),
          description: String(form.get("description") ?? ""),
          tags: String(form.get("tags") ?? ""),
          ...(form.get("product_id") ? { product_id: String(form.get("product_id")) } : {}),
        });
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
            <div className="grid grid-cols-2 gap-4">
              <Field label={t("kind")}>
                <Select name="kind" defaultValue="photo" className="w-full">
                  <option value="photo">{t("kindPhoto")}</option>
                  <option value="logo">{t("kindLogo")}</option>
                </Select>
              </Field>
              <Field label={t("source")}>
                <Select name="source" defaultValue="own" className="w-full">
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {t(`sources.${s}`)}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field label={t("description")} hint={t("descriptionHint")}>
              <Input name="description" maxLength={500} />
            </Field>
            <Field label={t("tags")} hint={t("tagsHint")}>
              <Input name="tags" maxLength={1000} />
            </Field>
            <Field label={t("product")} hint={t("productUploadHint")}>
              <Select name="product_id" defaultValue={productFilter} className="w-full">
                <option value="">{t("noProduct")}</option>
                {products.map((p) => (
                  <option key={p.product_id} value={p.product_id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
            <p className="text-xs text-muted md:col-span-2">{t("sourceHint")}</p>
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
        {logos.length === 0 ? (
          <p className="text-sm text-muted">{t("noLogo")}</p>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted">{t("logoHint")}</p>
            <div className="flex flex-wrap gap-4">
              {logos.map((l) => (
                <div key={l.asset_id} className={`space-y-2 rounded-md border p-2 ${l === logo ? "border-accent" : "border-border"}`}>
                  <img src={l.urls.thumb} alt={l.description || t("kindLogo")} className="h-20 w-auto rounded bg-white p-2" />
                  <p className="max-w-40 truncate text-xs text-muted">{l.description || l.filename}</p>
                  {l === logo ? (
                    <p className="text-xs text-accent">✓ {t("postLogo")}</p>
                  ) : (
                    canManage && (
                      <Button
                        variant="ghost"
                        className="px-2 py-1 text-xs"
                        onClick={async () => {
                          await api(`/tenants/${tenantId}/media/${l.asset_id}/default-logo`, { method: "POST" });
                          router.refresh();
                        }}
                      >
                        {t("useOnPosts")}
                      </Button>
                    )
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      <ProductsCard
        tenantId={tenantId}
        products={products}
        active={activeProduct}
        photos={activeProduct ? shown : []}
        canManage={canManage}
        onPick={(id) => setProductFilter(id)}
      />

      <Card title={activeProduct ? t("productPhotos", { name: activeProduct.name, count: shown.length }) : t("photosTitle", { count: photos.length })}>
        {canManage && photos.some((p) => !p.analysis && !p.parent_asset_id && p.status === "ready") && (
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <Button
              variant="ghost"
              onClick={async () => {
                try {
                  const r = await api<{ queued: number }>(`/tenants/${tenantId}/media/analyze-all`, { method: "POST" });
                  setError(null);
                  alert(t("analyzeAllDone", { count: r.queued }));
                } catch (err) {
                  setError(err instanceof ApiError ? err.message : tc("error"));
                }
                router.refresh();
              }}
            >
              {t("analyzeAll")}
            </Button>
            <span className="text-xs text-muted">{t("analyzeAllHint")}</span>
          </div>
        )}
        {allTags.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-2 text-xs">
            <Chip active={!filter} onClick={() => setFilter("")} label={t("allTags")} />
            {allTags.map((tag) => (
              <Chip key={tag} active={filter === tag} onClick={() => setFilter(tag)} label={tag} />
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
                {a.status === "ready" ? (
                  <img src={a.urls.thumb} alt={a.description || a.filename} className="aspect-square w-full object-cover" loading="lazy" />
                ) : (
                  <div className="flex aspect-square w-full items-center justify-center bg-bg text-xs text-muted">
                    {a.status === "pending" ? t("editing") : t("editFailed")}
                  </div>
                )}
                <div className="space-y-1 p-2 text-xs">
                  <Badges asset={a} />
                  {a.analysis && a.analysis.status !== "done" && (
                    <p className={a.analysis.status === "failed" ? "text-danger" : "text-accent"}>
                      {a.analysis.status === "failed" ? t("analysisFailed") : t("analyzing")}
                    </p>
                  )}
                  {a.analysis?.title_az && <p className="font-medium">{a.analysis.title_az}</p>}
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
          key={current.asset_id + current.status + current.focal_x + current.focal_y + current.enhance + current.approved_at}
          tenantId={tenantId}
          asset={current}
          assets={assets}
          products={products}
          hasLogo={Boolean(logo)}
          canManage={canManage}
          onSelect={setSelected}
        />
      )}
    </div>
  );
}

function ProductsCard({
  tenantId,
  products,
  active,
  photos,
  canManage,
  onPick,
}: {
  tenantId: string;
  products: ProductInfo[];
  active: ProductInfo | null;
  photos: MediaAsset[];
  canManage: boolean;
  onPick: (id: string) => void;
}) {
  const t = useTranslations("media");
  const tc = useTranslations("common");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<Format>("square");
  const [order, setOrder] = useState<string[] | null>(null);
  const ordered = order ? order.map((id) => photos.find((p) => p.asset_id === id)!).filter(Boolean) : photos;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    } finally {
      setBusy(false);
    }
  }

  async function onCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    await run(async () => {
      const p = await api<ProductInfo>(`/tenants/${tenantId}/products`, {
        method: "POST",
        body: { name: form.get("name"), category: form.get("category") ?? "" },
      });
      formEl.reset();
      onPick(p.product_id);
    });
  }

  function move(index: number, delta: number) {
    const ids = ordered.map((p) => p.asset_id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    setOrder(ids);
  }

  return (
    <Card title={t("productsTitle")}>
      <p className="mb-3 text-sm text-muted">{t("productsHint")}</p>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="mb-4 flex flex-wrap gap-2 text-xs">
        <Chip active={!active} onClick={() => { setOrder(null); onPick(""); }} label={t("allPhotos")} />
        {products.map((p) => (
          <Chip
            key={p.product_id}
            active={active?.product_id === p.product_id}
            onClick={() => { setOrder(null); onPick(p.product_id); }}
            label={`${p.name} (${p.photos})`}
          />
        ))}
      </div>
      {canManage && (
        <form onSubmit={onCreate} className="mb-4 flex flex-wrap items-end gap-3">
          <div className="min-w-48 flex-1">
            <Field label={t("productName")}>
              <Input name="name" required maxLength={200} />
            </Field>
          </div>
          <div className="min-w-40">
            <Field label={t("productCategory")}>
              <Input name="category" maxLength={200} />
            </Field>
          </div>
          <Button type="submit" disabled={busy}>
            {t("newProduct")}
          </Button>
        </form>
      )}

      {active && (
        <div className="space-y-3 border-t border-border pt-4">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-sm font-medium">{t("carouselTitle")}</span>
            <Chip active={format === "feed"} onClick={() => setFormat("feed")} label={t("previewFeed")} />
            <Chip active={format === "square"} onClick={() => setFormat("square")} label={t("previewSquare")} />
            <Chip active={format === "landscape"} onClick={() => setFormat("landscape")} label={t("previewLandscape")} />
          </div>
          <p className="text-xs text-muted">{t("carouselHint")}</p>
          {ordered.length === 0 ? (
            <p className="text-sm text-muted">{t("productEmpty")}</p>
          ) : (
            <div className="flex snap-x gap-3 overflow-x-auto pb-2">
              {ordered.map((p, i) => (
                <div key={p.asset_id} className="w-56 shrink-0 snap-start space-y-1">
                  {p.urls[format] ? (
                    <img src={p.urls[format]} alt="" className="w-full rounded border border-border" loading="lazy" />
                  ) : (
                    <div className="flex aspect-square items-center justify-center rounded border border-border text-xs text-muted">
                      {p.status === "pending" ? t("editing") : t("editFailed")}
                    </div>
                  )}
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted">
                      {i + 1}
                      {i === 0 ? ` · ${t("cover")}` : ""}
                      {!p.publishable ? ` · ${t("notPublishableShort")}` : ""}
                    </span>
                    {canManage && (
                      <span className="flex gap-1">
                        <button type="button" onClick={() => move(i, -1)} className="rounded border border-border px-2" aria-label={t("moveLeft")}>
                          ←
                        </button>
                        <button type="button" onClick={() => move(i, 1)} className="rounded border border-border px-2" aria-label={t("moveRight")}>
                          →
                        </button>
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {canManage && (
            <div className="flex flex-wrap gap-2">
              {order && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(`/tenants/${tenantId}/products/${active.product_id}/order`, { method: "PUT", body: { asset_ids: order } });
                      setOrder(null);
                    })
                  }
                >
                  {t("saveOrder")}
                </Button>
              )}
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  const name = prompt(t("productName"), active.name);
                  if (name && name.trim()) run(() => api(`/tenants/${tenantId}/products/${active.product_id}`, { method: "PATCH", body: { name } }));
                }}
              >
                {t("rename")}
              </Button>
              <Button
                variant="danger"
                disabled={busy}
                onClick={() =>
                  confirm(t("deleteProductConfirm")) &&
                  run(async () => {
                    await api(`/tenants/${tenantId}/products/${active.product_id}`, { method: "DELETE" });
                    onPick("");
                  })
                }
              >
                {t("deleteProduct")}
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function Chip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
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

function Badges({ asset }: { asset: MediaAsset }) {
  const t = useTranslations("media");
  const badge = "rounded-full border px-2 py-0.5";
  return (
    <div className="flex flex-wrap gap-1">
      {asset.source !== "own" && (
        <span className={`${badge} ${asset.source === "reference" ? "border-danger text-danger" : "border-border text-muted"}`}>
          {t(`sources.${asset.source}`)}
        </span>
      )}
      {asset.parent_asset_id && (
        <span className={`${badge} border-accent text-accent`}>AI · {(asset.edit?.kinds ?? []).map((k) => t(`kinds.${k}`)).join(", ")}</span>
      )}
      {asset.parent_asset_id && asset.status === "ready" && !asset.approved_at && (
        <span className={`${badge} border-danger text-danger`}>{t("needsApproval")}</span>
      )}
    </div>
  );
}

function PhotoEditor({
  tenantId,
  asset,
  assets,
  products,
  hasLogo,
  canManage,
  onSelect,
}: {
  tenantId: string;
  asset: MediaAsset;
  assets: MediaAsset[];
  products: ProductInfo[];
  hasLogo: boolean;
  canManage: boolean;
  onSelect: (id: string | null) => void;
}) {
  const t = useTranslations("media");
  const tc = useTranslations("common");
  const router = useRouter();
  const [description, setDescription] = useState(asset.description);
  const [tags, setTags] = useState(asset.tags.join(", "));
  const [source, setSource] = useState<MediaSource>(asset.source);
  const [productId, setProductId] = useState(asset.product_id ?? "");
  const [focal, setFocal] = useState({ x: asset.focal_x, y: asset.focal_y });
  const [enhance, setEnhance] = useState(asset.enhance);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [preview, setPreview] = useState<Format>(asset.analysis?.best_format ?? "feed");

  const parent = asset.parent_asset_id ? assets.find((a) => a.asset_id === asset.parent_asset_id) : null;
  const edits = assets.filter((a) => a.parent_asset_id === asset.asset_id);

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

  if (asset.status !== "ready") {
    return (
      <Card title={asset.filename}>
        {asset.status === "pending" ? <Alert>{t("editingLong")}</Alert> : <Alert tone="error">{asset.edit?.error ?? t("editFailed")}</Alert>}
        <div className="mt-4 flex gap-2">
          <Button variant="ghost" onClick={() => onSelect(null)}>
            {t("close")}
          </Button>
          {canManage && asset.status === "failed" && (
            <Button variant="danger" disabled={busy} onClick={() => run(async () => {
              await api(`/tenants/${tenantId}/media/${asset.asset_id}`, { method: "DELETE" });
              onSelect(null);
            })}>
              {t("delete")}
            </Button>
          )}
        </div>
      </Card>
    );
  }

  const previewUrl = asset.urls[hasLogo ? `${preview}-logo` : preview] ?? asset.urls[preview];

  return (
    <Card title={asset.filename}>
      <div className="mb-4">
        <Badges asset={asset} />
      </div>
      {parent && (
        <div className="mb-6 space-y-2">
          <p className="text-sm font-medium">{t("beforeAfter")}</p>
          <div className="grid grid-cols-2 gap-3">
            {parent.urls.thumb && <img src={parent.urls.thumb} alt={t("before")} className="w-full rounded border border-border" />}
            <img src={asset.urls.thumb} alt={t("after")} className="w-full rounded border border-accent" />
          </div>
          {asset.edit?.cost_usd && (
            <p className="text-xs text-muted">
              ${asset.edit.cost_usd}
              {asset.edit.cost_complete === false ? ` + ${t("costUnknownPart")}` : ""}
            </p>
          )}
          {canManage && !asset.approved_at && (
            <div className="flex items-center gap-3">
              <Button
                disabled={busy}
                onClick={() => run(() => api(`/tenants/${tenantId}/media/${asset.asset_id}/approve`, { method: "POST" }), t("approved"))}
              >
                {t("approve")}
              </Button>
              <span className="text-xs text-muted">{t("approveHint")}</span>
            </div>
          )}
        </div>
      )}

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
            <Chip active={preview === "feed"} onClick={() => setPreview("feed")} label={t("previewFeed")} />
            <Chip active={preview === "square"} onClick={() => setPreview("square")} label={t("previewSquare")} />
            <Chip active={preview === "landscape"} onClick={() => setPreview("landscape")} label={t("previewLandscape")} />
          </div>
          <img src={previewUrl} alt={t("previewAlt")} className="max-h-96 w-auto rounded border border-border" />
          <p className="text-xs text-muted">{asset.publishable ? t("previewHint") : t("notPublishable")}</p>
        </div>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Field label={t("description")} hint={t("descriptionHint")}>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} disabled={!canManage} maxLength={500} />
        </Field>
        <Field label={t("tags")} hint={t("tagsHint")}>
          <Input value={tags} onChange={(e) => setTags(e.target.value)} disabled={!canManage} />
        </Field>
        <Field label={t("product")}>
          <Select value={productId} onChange={(e) => setProductId(e.target.value)} disabled={!canManage} className="w-full">
            <option value="">{t("noProduct")}</option>
            {products.map((p) => (
              <option key={p.product_id} value={p.product_id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("source")} hint={t("sourceHint")}>
          <Select value={source} onChange={(e) => setSource(e.target.value as MediaSource)} disabled={!canManage} className="w-full">
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {t(`sources.${s}`)}
              </option>
            ))}
          </Select>
        </Field>
        <label className="flex items-center gap-2 self-end text-sm">
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
                      source,
                      product_id: productId || null,
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
        <Button variant="ghost" onClick={() => onSelect(null)}>
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
                onSelect(null);
              })
            }
          >
            {t("delete")}
          </Button>
        )}
      </div>

      {!asset.parent_asset_id && (
        <AnalysisPanel tenantId={tenantId} asset={asset} canManage={canManage} onDone={() => router.refresh()} />
      )}

      {canManage && !asset.parent_asset_id && (
        <RecipeEditor tenantId={tenantId} asset={asset} assets={assets} onDone={() => router.refresh()} />
      )}

      {edits.length > 0 && (
        <div className="mt-6">
          <p className="mb-2 text-sm font-medium">{t("editsOfThis", { count: edits.length })}</p>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
            {edits.map((e) => (
              <button key={e.asset_id} type="button" onClick={() => onSelect(e.asset_id)} className="overflow-hidden rounded border border-border text-left text-xs hover:border-accent">
                {e.status === "ready" ? (
                  <img src={e.urls.thumb} alt="" className="aspect-square w-full object-cover" />
                ) : (
                  <div className="flex aspect-square items-center justify-center bg-bg p-1 text-center text-muted">
                    {e.status === "pending" ? t("editing") : t("editFailed")}
                  </div>
                )}
                <div className="p-1">{(e.edit?.kinds ?? []).map((k) => t(`kinds.${k}`)).join(", ")}</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function AnalysisPanel({
  tenantId,
  asset,
  canManage,
  onDone,
}: {
  tenantId: string;
  asset: MediaAsset;
  canManage: boolean;
  onDone: () => void;
}) {
  const t = useTranslations("media");
  const tc = useTranslations("common");
  const [error, setError] = useState<string | null>(null);
  const a: PhotoAnalysis | null = asset.analysis;
  const rows: [string, string | undefined][] = a
    ? [
        ["aCategory", a.category],
        ["aRoom", a.room ?? undefined],
        ["aStyle", a.style?.join(", ")],
        ["aColors", a.colors?.join(", ")],
        ["aMaterials", a.materials_visible?.join(", ")],
        ["aFeatures", a.features?.join(", ")],
      ]
    : [];

  async function rerun() {
    setError(null);
    try {
      await api(`/tenants/${tenantId}/media/${asset.asset_id}/analyze`, { method: "POST" });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : tc("error"));
    }
  }

  return (
    <div className="mt-6 space-y-3 rounded-md border border-border p-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm font-medium">{t("analysisTitle")}</p>
        {a?.status === "done" && a.looks_like && <span className="text-xs text-muted">{t(`looksLike.${a.looks_like}`)}</span>}
        {canManage && a?.status !== "queued" && a?.status !== "running" && (
          <Button variant="ghost" className="ml-auto px-2 py-1 text-xs" onClick={rerun}>
            {a ? t("reanalyze") : t("analyze")}
          </Button>
        )}
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {!a && <p className="text-sm text-muted">{t("notAnalyzed")}</p>}
      {(a?.status === "queued" || a?.status === "running") && <Alert>{t("analyzingLong")}</Alert>}
      {a?.status === "failed" && <Alert tone="error">{a.error ?? t("analysisFailed")}</Alert>}
      {a?.status === "done" && (
        <div className="space-y-3 text-sm">
          {a.title_az && <p className="font-medium">{a.title_az}</p>}
          {a.product_action && <p className="text-xs text-accent">{t(`productAction.${a.product_action}`)}</p>}
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
            {rows
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="text-muted">{t(k)}:</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            {a.best_format && (
              <div className="flex gap-2">
                <dt className="text-muted">{t("aBestFormat")}:</dt>
                <dd>{t(`formats.${a.best_format}`)}</dd>
              </div>
            )}
          </dl>
          {a.hashtags && a.hashtags.length > 0 && (
            <div>
              <p className="text-xs text-muted">{t("aHashtags")}</p>
              <p className="text-accent">{a.hashtags.join(" ")}</p>
            </div>
          )}
          {a.quality_issues && a.quality_issues.length > 0 && (
            <div>
              <p className="text-xs text-muted">{t("aQuality")}</p>
              <div className="flex flex-wrap gap-1">
                {a.quality_issues.map((q) => (
                  <span key={q} className="rounded-full border border-danger px-2 py-0.5 text-xs text-danger">
                    {t(`quality.${q}`)}
                  </span>
                ))}
              </div>
              {a.suggested_edits && a.suggested_edits.length > 0 && (
                <ul className="mt-1 list-disc ps-5 text-xs text-muted">
                  {a.suggested_edits.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const STEPS = ["remove", "background", "recolor", "swap"] as const;
type StepKey = (typeof STEPS)[number];

function RecipeEditor({
  tenantId,
  asset,
  assets,
  onDone,
}: {
  tenantId: string;
  asset: MediaAsset;
  assets: MediaAsset[];
  onDone: () => void;
}) {
  const t = useTranslations("media");
  const tc = useTranslations("common");
  const [recipe, setRecipe] = useState<Recipe>({ ...EMPTY_RECIPE, ...(asset.recipe ?? {}) });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const others = assets.filter((a) => a.kind === "photo" && a.status === "ready" && a.asset_id !== asset.asset_id);
  const anyOn = recipe.enhance || STEPS.some((k) => recipe[k].on);

  const setStep = (key: StepKey, patch: Partial<RecipeStep>) =>
    setRecipe((r) => ({ ...r, [key]: { ...r[key], ...patch } }));

  async function send(path: string, method: "PUT" | "POST", done: string) {
    setBusy(true);
    setMessage(null);
    try {
      await api(`/tenants/${tenantId}/media/${asset.asset_id}/${path}`, { method, body: recipe });
      setMessage({ tone: "success", text: done });
      onDone();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof ApiError ? err.message : tc("error") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 space-y-4 rounded-md border border-border p-4">
      <div>
        <p className="text-sm font-medium">{t("recipeTitle")}</p>
        <p className="text-xs text-muted">{t("recipeHint")}</p>
      </div>
      <Field label={t("aiSubject")} hint={t("aiSubjectHint")}>
        <Input value={recipe.subject} onChange={(e) => setRecipe((r) => ({ ...r, subject: e.target.value }))} maxLength={200} />
      </Field>

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={recipe.enhance} onChange={(e) => setRecipe((r) => ({ ...r, enhance: e.target.checked }))} />
        <span className="font-medium">{t("kinds.enhance")}</span>
        <span className="text-xs text-muted">{t("enhanceAiHint")}</span>
      </label>

      {STEPS.map((key) => {
        const step = recipe[key];
        const withReference = key === "background" || key === "swap";
        return (
          <div key={key} className={`space-y-2 rounded-md border p-3 ${step.on ? "border-accent" : "border-border"}`}>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={step.on} onChange={(e) => setStep(key, { on: e.target.checked })} />
              <span className="font-medium">{t(`kinds.${key}`)}</span>
            </label>
            {step.on && (
              <div className="grid gap-3 md:grid-cols-2">
                <div className={withReference ? "" : "md:col-span-2"}>
                  <Field label={t("aiRequest")} hint={t(`aiRequestHint.${key}`)}>
                    <textarea
                      value={step.request}
                      onChange={(e) => setStep(key, { request: e.target.value })}
                      rows={2}
                      maxLength={500}
                      className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                    />
                  </Field>
                </div>
                {withReference && (
                  <Field label={t("aiReference")} hint={t(`aiReferenceHint.${key}`)}>
                    <Select
                      value={step.reference_asset_id ?? ""}
                      onChange={(e) => setStep(key, { reference_asset_id: e.target.value || null })}
                      className="w-full"
                    >
                      <option value="">—</option>
                      {others.map((o) => (
                        <option key={o.asset_id} value={o.asset_id}>
                          {o.description || o.filename}
                          {o.source === "reference" ? ` (${t("sources.reference")})` : ""}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
              </div>
            )}
          </div>
        );
      })}

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => send("edits", "POST", t("editStarted"))} disabled={busy || !anyOn}>
          {t("aiSubmit")}
        </Button>
        <Button variant="ghost" onClick={() => send("recipe", "PUT", t("recipeSaved"))} disabled={busy}>
          {t("recipeSave")}
        </Button>
        <span className="text-xs text-muted">{t("aiCostHint")}</span>
      </div>
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
    </div>
  );
}
