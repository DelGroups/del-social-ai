"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { CopyField } from "@/components/client";
import { Alert, Button, Card, Field, Input } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import type { BrandProfileData, ChannelInfo } from "@/lib/types";

const IG_NAME_MAX = 30;
const IG_BIO_MAX = 150;
const FB_ABOUT_MAX = 255;

/** Short category names: "Ofis mebelləri (İclas masaları, …)" → "Ofis mebelləri". */
function shortCategories(categories: string[]): string[] {
  return categories.map((c) => c.replace(/\s*\(.*\)\s*/, "").trim()).filter(Boolean);
}

function suggestedBio(p: BrandProfileData): string {
  const lines = [
    p.claims[0] ?? "",
    shortCategories(p.products.categories).slice(0, 4).join(" · "),
    p.basics.working_hours ? `🕘 ${p.basics.working_hours}` : "",
  ].filter(Boolean);
  return lines.join("\n").slice(0, IG_BIO_MAX);
}

type Props = { tenantId: string; channels: ChannelInfo[]; profile: BrandProfileData | null; manage: boolean };

export function PageSetup({ tenantId, channels, profile, manage }: Props) {
  const t = useTranslations("pageSetup");
  const tc = useTranslations("common");
  const fb = channels.find((c) => c.channel === "facebook")?.connections[0];
  const ig = channels.find((c) => c.channel === "instagram")?.connections[0];
  const b = profile?.basics ?? {};
  const description = String(b.description ?? "");
  const [about, setAbout] = useState(description.slice(0, FB_ABOUT_MAX));
  const [fullDescription, setFullDescription] = useState(description);
  const [website, setWebsite] = useState(String(b.website ?? ""));
  const [phone, setPhone] = useState(String(b.phone ?? ""));
  const [emails, setEmails] = useState("");
  const [igName, setIgName] = useState(`${String(b.company_name ?? "")} | Mebel sifarişi`.slice(0, IG_NAME_MAX));
  const [igBio, setIgBio] = useState(profile ? suggestedBio(profile) : "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  if (!manage || (!fb && !ig)) return null;

  async function applyFacebook() {
    setBusy(true);
    setMessage(null);
    try {
      await api(`/tenants/${tenantId}/connections/${fb!.connection_id}/page-profile`, {
        method: "POST",
        body: { about, description: fullDescription, website, phone, emails: emails || null },
      });
      setMessage({ tone: "success", text: t("fbDone") });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof ApiError ? err.message : tc("error") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={t("title")} className="mt-6">
      <p className="mb-4 text-sm text-muted">{t("intro")}</p>
      <div className="grid gap-6 lg:grid-cols-2">
        {fb && (
          <div className="space-y-3">
            <p className="font-medium">Facebook · {fb.display_name}</p>
            <Field label={t("about")} hint={`${about.length}/${FB_ABOUT_MAX}`}>
              <Input value={about} onChange={(e) => setAbout(e.target.value.slice(0, FB_ABOUT_MAX))} />
            </Field>
            <Field label={t("description")}>
              <textarea
                value={fullDescription}
                onChange={(e) => setFullDescription(e.target.value)}
                rows={4}
                className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("website")}>
                <Input value={website} onChange={(e) => setWebsite(e.target.value)} />
              </Field>
              <Field label={t("phone")}>
                <Input value={phone} onChange={(e) => setPhone(e.target.value)} />
              </Field>
            </div>
            <Field label={t("emails")} hint={t("emailsHint")}>
              <Input value={emails} onChange={(e) => setEmails(e.target.value)} />
            </Field>
            <Button onClick={applyFacebook} disabled={busy}>
              {t("fbApply")}
            </Button>
            <p className="text-xs text-muted">{t("fbManual")}</p>
          </div>
        )}
        {ig && (
          <div className="space-y-3">
            <p className="font-medium">Instagram · {ig.display_name}</p>
            <Alert>{t("igManual")}</Alert>
            <Field label={t("igName")} hint={`${igName.length}/${IG_NAME_MAX}`}>
              <Input value={igName} onChange={(e) => setIgName(e.target.value.slice(0, IG_NAME_MAX))} />
            </Field>
            <CopyField value={igName} />
            <Field label={t("igBio")} hint={`${igBio.length}/${IG_BIO_MAX}`}>
              <textarea
                value={igBio}
                onChange={(e) => setIgBio(e.target.value.slice(0, IG_BIO_MAX))}
                rows={4}
                className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
              />
            </Field>
            <CopyField value={igBio} />
            {website && (
              <>
                <p className="text-sm">{t("igLink")}</p>
                <CopyField value={website} />
              </>
            )}
            <p className="text-xs text-muted">{t("igSteps")}</p>
          </div>
        )}
      </div>
      {message && (
        <div className="mt-4">
          <Alert tone={message.tone}>{message.text}</Alert>
        </div>
      )}
    </Card>
  );
}
