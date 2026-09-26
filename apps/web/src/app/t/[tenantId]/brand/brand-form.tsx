"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert, Button, Card, Field, Input, Select } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import { formatDateTime } from "@/lib/prefs";
import type { BrandProfileData, BrandProfileOut } from "@/lib/types";

// Mirrors apps/api/del_social/knowledge/brand_profile.py. Labels: messages brand.f.<path>
type Kind = "text" | "textarea" | "list" | "blocks" | "select" | "number" | "bool";
type Spec = { path: string; kind: Kind; options?: string[] };

const SECTIONS: { key: string; fields: Spec[] }[] = [
  {
    key: "basics",
    fields: [
      { path: "basics.company_name", kind: "text" },
      { path: "basics.description", kind: "textarea" },
      { path: "basics.cities", kind: "list" },
      { path: "basics.showroom_address", kind: "text" },
      { path: "basics.working_hours", kind: "text" },
      { path: "basics.website", kind: "text" },
      { path: "basics.phone", kind: "text" },
      { path: "basics.whatsapp", kind: "text" },
    ],
  },
  {
    key: "audience",
    fields: [
      { path: "audience.description", kind: "textarea" },
      { path: "audience.segments", kind: "list" },
    ],
  },
  {
    key: "products",
    fields: [
      { path: "products.categories", kind: "list" },
      { path: "products.materials", kind: "list" },
      { path: "products.usps", kind: "list" },
    ],
  },
  {
    key: "voice",
    fields: [
      { path: "voice.tone_words", kind: "list" },
      { path: "voice.formality", kind: "select", options: ["formal", "friendly"] },
      { path: "voice.emoji", kind: "select", options: ["none", "few", "many"] },
      { path: "voice.caption_length", kind: "select", options: ["short", "medium", "long"] },
      { path: "languages.mode", kind: "select", options: ["az_ru_same_caption", "az", "ru", "alternate"] },
      { path: "voice.notes", kind: "textarea" },
    ],
  },
  {
    key: "rules",
    fields: [
      { path: "never.words", kind: "list" },
      { path: "never.topics", kind: "list" },
      { path: "never.competitors", kind: "list" },
      { path: "claims", kind: "list" },
      { path: "terminology", kind: "list" },
      { path: "ctas", kind: "list" },
    ],
  },
  {
    key: "hashtags",
    fields: [
      { path: "hashtags.branded", kind: "list" },
      { path: "hashtags.pool", kind: "list" },
      { path: "hashtags.max_per_post", kind: "number" },
    ],
  },
  {
    key: "examples",
    fields: [
      { path: "examples.good", kind: "blocks" },
      { path: "examples.bad", kind: "blocks" },
    ],
  },
  { key: "occasions", fields: [{ path: "occasions", kind: "list" }] },
  {
    key: "image_editing",
    fields: [
      { path: "image_editing.enhance", kind: "bool" },
      { path: "image_editing.remove_objects", kind: "bool" },
      { path: "image_editing.background", kind: "bool" },
      { path: "image_editing.recolor", kind: "bool" },
      { path: "image_editing.swap_product", kind: "bool" },
    ],
  },
];

const BLOCK_SEPARATOR = /\n\s*---\s*\n/;

type Obj = Record<string, unknown>;

function getPath(obj: Obj, path: string): unknown {
  return path.split(".").reduce<unknown>((o, k) => (o as Obj)?.[k], obj);
}

function setPath(obj: Obj, path: string, value: unknown): Obj {
  const [head, ...rest] = path.split(".");
  return { ...obj, [head]: rest.length ? setPath((obj[head] as Obj) ?? {}, rest.join("."), value) : value };
}

/** Text shown in the field → value stored in the profile. */
function toText(kind: Kind, value: unknown): string {
  if (kind === "list") return ((value as string[]) ?? []).join("\n");
  if (kind === "blocks") return ((value as string[]) ?? []).join("\n---\n");
  return String(value ?? "");
}

function fromText(kind: Kind, text: string): unknown {
  if (kind === "list") return text.split("\n").map((s) => s.trim()).filter(Boolean);
  if (kind === "blocks") return text.split(BLOCK_SEPARATOR).map((s) => s.trim()).filter(Boolean);
  if (kind === "number") return Number(text) || 0;
  if (kind === "bool") return text === "true";
  return text;
}

type Props = { tenantId: string; canEdit: boolean; initial: BrandProfileOut };

export function BrandForm({ tenantId, canEdit, initial }: Props) {
  const t = useTranslations("brand");
  const tc = useTranslations("common");
  const router = useRouter();
  const [data, setData] = useState<BrandProfileData>(initial.data);
  // Lists are edited as raw text so blank lines and spaces don't jump around while typing
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [version, setVersion] = useState(initial.version);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const textOf = (s: Spec) => drafts[s.path] ?? toText(s.kind, getPath(data as Obj, s.path));
  const update = (s: Spec, text: string) => {
    setDrafts((d) => ({ ...d, [s.path]: text }));
    setData((d) => setPath(d as Obj, s.path, fromText(s.kind, text)) as BrandProfileData);
  };

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const saved = await api<BrandProfileOut>(`/tenants/${tenantId}/brand-profile`, {
        method: "PUT",
        body: { base_version: version, data },
      });
      setVersion(saved.version);
      setData(saved.data);
      setDrafts({});
      setMessage({ tone: "success", text: t("saved", { version: saved.version }) });
      router.refresh();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof ApiError ? err.message : tc("error") });
    } finally {
      setBusy(false);
    }
  }

  function input(s: Spec) {
    if (s.kind === "bool") {
      return (
        <input
          type="checkbox"
          name={s.path}
          disabled={!canEdit}
          checked={getPath(data as Obj, s.path) === true}
          onChange={(e) => update(s, String(e.target.checked))}
          className="h-4 w-4"
        />
      );
    }
    const common = { name: s.path, disabled: !canEdit, value: textOf(s) };
    if (s.kind === "select") {
      return (
        <Select {...common} className="w-full" onChange={(e) => update(s, e.target.value)}>
          {s.options!.map((o) => (
            <option key={o} value={o}>
              {t(`opt.${o}`)}
            </option>
          ))}
        </Select>
      );
    }
    if (s.kind === "text" || s.kind === "number") {
      return (
        <Input
          {...common}
          type={s.kind === "number" ? "number" : "text"}
          min={s.kind === "number" ? 0 : undefined}
          max={s.kind === "number" ? 30 : undefined}
          maxLength={s.kind === "text" ? 200 : undefined}
          onChange={(e) => update(s, e.target.value)}
        />
      );
    }
    return (
      <textarea
        {...common}
        rows={s.kind === "blocks" ? 8 : 4}
        onChange={(e) => update(s, e.target.value)}
        className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-70"
      />
    );
  }

  const hint = (s: Spec) => (s.kind === "list" ? t("listHint") : s.kind === "blocks" ? t("blocksHint") : undefined);

  return (
    <form onSubmit={onSave} className="space-y-6">
      <p className="text-sm text-muted">{t("intro")}</p>
      <p className="text-sm text-muted">
        {initial.version === 0
          ? t("noVersion")
          : t("version", {
              version: initial.version,
              date: initial.created_at ? formatDateTime(initial.created_at) : "",
              email: initial.created_by_email ?? "—",
            })}
      </p>
      {!canEdit && <Alert>{t("readOnly")}</Alert>}

      {SECTIONS.map((section) => (
        <Card key={section.key} title={t(`sections.${section.key}`)}>
          {section.key === "image_editing" && <p className="mb-4 text-sm text-muted">{t("imageEditingHint")}</p>}
          <div className="grid gap-4 md:grid-cols-2">
            {section.fields.map((s) => (
              <div key={s.path} className={s.kind === "text" || s.kind === "select" || s.kind === "number" ? "" : "md:col-span-2"}>
                <Field label={t(`f.${s.path}`)} hint={hint(s)}>
                  {input(s)}
                </Field>
              </div>
            ))}
          </div>
        </Card>
      ))}

      <Alert>{t("pricesRule")}</Alert>
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
      {canEdit && (
        <div className="sticky bottom-0 -mx-4 border-t border-border bg-bg px-4 py-3">
          <Button type="submit" disabled={busy}>
            {t("save")}
          </Button>
        </div>
      )}
    </form>
  );
}
