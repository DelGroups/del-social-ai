"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert, Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { MediaAsset, PostInfo } from "@/lib/types";

import { StatusBadge } from "../status-badge";

const CAPTION_MAX = 2200;
const VERDICT: Record<string, string> = {
  pass: "border-success text-success",
  fix: "border-accent text-accent",
  block: "border-danger text-danger",
};

type Props = { tenantId: string; post: PostInfo; productPhotos: MediaAsset[]; canApprove: boolean };

export function PostEditor({ tenantId, post, productPhotos, canApprove }: Props) {
  const t = useTranslations("posts");
  const tc = useTranslations("common");
  const router = useRouter();
  const [caption, setCaption] = useState(post.caption ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [slide, setSlide] = useState(0);
  const [order, setOrder] = useState<string[]>(post.photos.map((p) => p.asset_id));
  const orderChanged = order.join() !== post.photos.map((p) => p.asset_id).join();
  const thumbs = new Map(productPhotos.map((m) => [m.asset_id, m.urls.thumb]));
  const postUrls = new Map(post.photos.map((p) => [p.asset_id, p.url]));
  const addable = productPhotos.filter((m) => !order.includes(m.asset_id));

  function move(i: number, delta: number) {
    const next = [...order];
    const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setOrder(next);
  }
  const working = post.status === "generating" || post.status === "publishing";
  const editable = canApprove && (post.status === "ready" || post.status === "approved");
  const canPublish = canApprove && ["ready", "approved", "partly_published"].includes(post.status) && caption.trim().length > 0;
  const base = `/tenants/${tenantId}/posts/${post.post_id}`;

  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => router.refresh(), 4000);
    return () => clearInterval(timer);
  }, [working, router]);

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

  async function publish() {
    if (caption !== post.caption) await api(base, { method: "PATCH", body: { caption } });
    await api(`${base}/publish`, { method: "POST", body: { confirm: true } });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <StatusBadge status={post.status} />
        <span className="text-muted">
          {post.channels.join(" + ")} · {post.format} · {post.with_logo ? t("withLogo") : t("noLogo")} · {formatDateTime(post.created_at)}
        </span>
        {post.cost_usd && <span className="text-muted">${Number(post.cost_usd).toFixed(3)}</span>}
      </div>
      {post.error && <Alert tone="error">{post.error}</Alert>}
      {post.status === "generating" && <Alert>{t("generatingLong")}</Alert>}
      {post.status === "publishing" && <Alert>{t("publishingLong")}</Alert>}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={t("preview")}>
          {editable && (
            <div className="mb-4 space-y-2">
              <p className="text-xs text-muted">{t("orderHint")}</p>
              <div className="flex flex-wrap gap-2">
                {order.map((id, i) => (
                  <div key={id} className="w-24 space-y-1 text-center text-xs">
                    <img src={postUrls.get(id) ?? thumbs.get(id)} alt="" className="h-20 w-24 rounded border border-border object-cover" />
                    <div className="flex justify-center gap-1">
                      <button type="button" onClick={() => move(i, -1)} className="rounded border border-border px-1.5" aria-label="←">←</button>
                      <button type="button" onClick={() => move(i, 1)} className="rounded border border-border px-1.5" aria-label="→">→</button>
                      {order.length > 1 && (
                        <button type="button" onClick={() => setOrder(order.filter((x) => x !== id))} className="rounded border border-danger px-1.5 text-danger" aria-label="✕">✕</button>
                      )}
                    </div>
                    <span className="text-muted">{i === 0 ? t("cover") : i + 1}</span>
                  </div>
                ))}
                {addable.length > 0 && order.length < 10 && (
                  <select
                    value=""
                    onChange={(e) => e.target.value && setOrder([...order, e.target.value])}
                    className="h-20 w-28 rounded border border-dashed border-border bg-bg px-1 text-xs text-muted"
                  >
                    <option value="">+ {t("addPhoto")}</option>
                    {addable.map((m) => (
                      <option key={m.asset_id} value={m.asset_id}>
                        {m.analysis?.title_az || m.description || m.filename}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {orderChanged && (
                <Button
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(base, { method: "PATCH", body: { asset_ids: order } });
                      setSlide(0);
                    }, t("orderSaved"))
                  }
                >
                  {t("saveOrder")}
                </Button>
              )}
            </div>
          )}
          {post.photos.length > 0 && (
            <div className="space-y-2">
              <img src={post.photos[slide]?.url} alt="" className="w-full rounded border border-border" />
              {post.photos.length > 1 && (
                <div className="flex items-center justify-between text-sm">
                  <Button variant="ghost" onClick={() => setSlide((s) => Math.max(0, s - 1))} disabled={slide === 0}>
                    ←
                  </Button>
                  <span className="text-muted">
                    {slide + 1} / {post.photos.length}
                  </span>
                  <Button variant="ghost" onClick={() => setSlide((s) => Math.min(post.photos.length - 1, s + 1))} disabled={slide === post.photos.length - 1}>
                    →
                  </Button>
                </div>
              )}
            </div>
          )}
          <pre className="mt-4 whitespace-pre-wrap font-sans text-sm leading-relaxed">{caption || t("writing")}</pre>
        </Card>

        <div className="space-y-4">
          {post.question && <Alert>❓ {post.question}</Alert>}
          {post.options.length > 0 && (
            <Card title={t("options")}>
              <div className="space-y-3">
                {post.options.map((o, i) => (
                  <button
                    key={i}
                    type="button"
                    disabled={!editable || busy}
                    onClick={() =>
                      run(async () => {
                        const updated = await api<PostInfo>(base, { method: "PATCH", body: { chosen_option: i } });
                        setCaption(updated.caption ?? "");
                      })
                    }
                    className={`w-full rounded-md border p-3 text-left text-sm transition ${post.chosen_option === i ? "border-accent" : "border-border hover:border-accent"}`}
                  >
                    <div className="mb-1 flex items-center gap-2 text-xs">
                      <span className="font-semibold">#{i + 1}</span>
                      <span className={`rounded-full border px-2 py-0.5 ${VERDICT[o.verdict] ?? ""}`}>{t(`verdict.${o.verdict}`)}</span>
                      <span className="truncate text-muted">{o.angle}</span>
                    </div>
                    <p className="line-clamp-3">{o.caption_az}</p>
                  </button>
                ))}
              </div>
            </Card>
          )}

          {post.status !== "generating" && (
            <Card title={t("finalCaption")}>
              <textarea
                value={caption}
                onChange={(e) => setCaption(e.target.value.slice(0, CAPTION_MAX))}
                disabled={!editable}
                rows={14}
                className="w-full rounded-md border border-border bg-bg px-3 py-2 font-sans text-sm text-text focus:border-accent focus:outline-none"
              />
              <p className="mt-1 text-xs text-muted">
                {caption.length}/{CAPTION_MAX}
              </p>
              {editable && caption !== post.caption && (
                <Button variant="ghost" className="mt-2" disabled={busy} onClick={() => run(() => api(base, { method: "PATCH", body: { caption } }), t("saved"))}>
                  {t("saveCaption")}
                </Button>
              )}
            </Card>
          )}

          {Object.keys(post.results).length > 0 && (
            <Card title={t("results")}>
              <ul className="space-y-1 text-sm">
                {Object.entries(post.results).map(([channel, r]) => (
                  <li key={channel}>
                    <span className="font-medium">{channel}:</span>{" "}
                    {r.url ? (
                      <a href={r.url} target="_blank" rel="noreferrer" className="text-accent underline">
                        {t("openPost")}
                      </a>
                    ) : (
                      <span className="text-danger">{r.error}</span>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {message && <Alert tone={message.tone}>{message.text}</Alert>}
          <div className="flex flex-wrap gap-2">
            {canPublish && (
              <Button
                disabled={busy}
                onClick={() => confirm(t("publishConfirm", { channels: post.channels.join(" + ") })) && run(publish, t("publishStarted"))}
              >
                {post.status === "partly_published" ? t("retryPublish") : t("publish")}
              </Button>
            )}
            {canApprove && (post.status === "ready" || post.status === "failed") && (
              <Button variant="ghost" disabled={busy} onClick={() => run(() => api(`${base}/regenerate`, { method: "POST" }))}>
                {t("regenerate")}
              </Button>
            )}
            {canApprove && !working && post.status !== "published" && (
              <Button
                variant="danger"
                disabled={busy}
                onClick={() =>
                  confirm(t("archiveConfirm")) &&
                  run(async () => {
                    await api(`${base}/archive`, { method: "POST" });
                    router.push(`/t/${tenantId}/posts`);
                  })
                }
              >
                {t("archive")}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
