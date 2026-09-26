"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { ChannelInfo, ChannelName, Connection, PageOption } from "@/lib/types";

// Brand names: the same in every language
const CHANNEL_NAMES: Record<ChannelName, string> = {
  instagram: "Instagram",
  facebook: "Facebook",
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  tiktok: "TikTok",
  youtube: "YouTube",
};

// ?meta=<reason> set by the API's Meta callback → message key
const NOTICES: Record<string, string> = {
  cancelled: "metaCancelled",
  error: "metaError",
  nopages: "metaNopages",
  session: "metaSession",
  forbidden: "metaForbidden",
  expired: "pickExpired",
};

type Props = {
  tenantId: string;
  manage: boolean;
  channels: ChannelInfo[];
  notice: string | null;
  pick: { id: string; pages: PageOption[] | null } | null;
};

export function ConnectionsManager({ tenantId, manage, channels, notice, pick }: Props) {
  const t = useTranslations();
  const format = useFormatter();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const base = `/tenants/${tenantId}/connections`;
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  }

  async function startMeta() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await api<{ url: string }>(`${base}/meta/start`, { method: "POST" });
      window.location.href = url; // Facebook's sign-in page; it sends the browser back to our callback
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.error"));
      setBusy(false);
    }
  }

  async function onPick(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const pageId = new FormData(e.currentTarget).get("page_id");
    await run(async () => {
      await api(`${base}/meta/pick/${encodeURIComponent(pick!.id)}`, { method: "POST", body: { page_id: pageId } });
      router.replace(`/t/${tenantId}/connections`);
    });
  }

  async function onTelegram(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const token = new FormData(formEl).get("bot_token");
    await run(async () => {
      await api(`${base}/telegram`, { method: "POST", body: { bot_token: token } });
      formEl.reset();
    });
  }

  function connectArea(c: ChannelInfo) {
    if (!manage) return null;
    if (!c.available) return <p className="text-sm text-muted">{t("connections.comingSoon")}</p>;
    if (!c.configured) return <p className="text-sm text-muted">{t("connections.notConfigured")}</p>;
    if (c.channel === "telegram") {
      return (
        <form onSubmit={onTelegram} className="space-y-3">
          <Field label={t("connections.telegramToken")} hint={t("connections.telegramHint")}>
            <Input name="bot_token" type="password" autoComplete="off" required maxLength={100} />
          </Field>
          <Button type="submit" disabled={busy}>
            {t("connections.connect")}
          </Button>
        </form>
      );
    }
    return (
      <div className="space-y-2">
        <Button onClick={startMeta} disabled={busy}>
          {t("connections.connectMeta")}
        </Button>
        <p className="text-xs text-muted">{t("connections.metaHint")}</p>
      </div>
    );
  }

  function connectionRow(conn: Connection) {
    const ok = conn.status === "active";
    return (
      <li key={conn.connection_id} className="space-y-2 rounded-md border border-border p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{conn.display_name}</span>
          <span
            className={`rounded-full border px-2 py-0.5 text-xs ${ok ? "border-success text-success" : "border-danger text-danger"}`}
          >
            {ok ? t("connections.statusActive") : t("connections.statusError")}
          </span>
          {conn.details.page_name && <span className="text-xs text-muted">· {conn.details.page_name}</span>}
        </div>
        {conn.last_error && <p className="text-xs text-danger">{conn.last_error}</p>}
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
          {conn.last_checked_at && <span>{t("connections.lastChecked", { date: date(conn.last_checked_at) })}</span>}
          {conn.token_expires_at && <span>{t("connections.expires", { date: date(conn.token_expires_at) })}</span>}
        </div>
        {manage && (
          <div className="flex gap-2">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => run(() => api(`${base}/${conn.connection_id}/test`, { method: "POST" }))}
            >
              {t("connections.test")}
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() =>
                confirm(t("connections.disconnectConfirm", { name: conn.display_name })) &&
                run(() => api(`${base}/${conn.connection_id}`, { method: "DELETE" }))
              }
            >
              {t("connections.disconnect")}
            </Button>
          </div>
        )}
      </li>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">{t("connections.intro")}</p>
      {notice && NOTICES[notice] && <Alert tone="error">{t(`connections.${NOTICES[notice]}`)}</Alert>}
      {error && <Alert tone="error">{error}</Alert>}

      {pick && (
        <Card title={t("connections.pickTitle")}>
          {pick.pages === null ? (
            <Alert tone="error">{t("connections.pickExpired")}</Alert>
          ) : (
            <form onSubmit={onPick} className="space-y-3">
              <p className="text-sm text-muted">{t("connections.pickHint")}</p>
              <ul className="space-y-2">
                {pick.pages.map((p, i) => (
                  <li key={p.page_id}>
                    <label className="flex cursor-pointer items-center gap-3 rounded-md border border-border p-3 text-sm">
                      <input type="radio" name="page_id" value={p.page_id} defaultChecked={i === 0} required />
                      <span className="font-medium">{p.name}</span>
                      <span className="text-muted">
                        {p.instagram_username ? `Instagram @${p.instagram_username}` : t("connections.noInstagram")}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <Button type="submit" disabled={busy}>
                {t("connections.pickSubmit")}
              </Button>
            </form>
          )}
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {channels.map((c) => (
          <Card key={c.channel} title={CHANNEL_NAMES[c.channel]}>
            <div className="space-y-4">
              {c.connections.length > 0 ? (
                <ul className="space-y-2">{c.connections.map(connectionRow)}</ul>
              ) : (
                <p className="text-sm text-muted">{t("connections.none")}</p>
              )}
              {connectArea(c)}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
