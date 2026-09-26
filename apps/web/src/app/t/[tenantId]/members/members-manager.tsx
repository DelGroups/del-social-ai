"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CopyField } from "@/components/client";
import { Alert, Button, Card, Field, Input, Select } from "@/components/ui";
import { ApiError, api } from "@/lib/client-api";
import {
  type Invitation,
  type Member,
  ROLES,
  type Role,
  canManageMembers,
  canManageOwners,
} from "@/lib/types";

type Props = {
  tenantId: string;
  myAccountId: string;
  myRole: Role;
  members: Member[];
  invitations: Invitation[];
};

export function MembersManager({ tenantId, myAccountId, myRole, members, invitations }: Props) {
  const t = useTranslations();
  const format = useFormatter();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ email: string; url: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const manage = canManageMembers(myRole);
  // Admins can't create, change or remove owners (the API enforces the same rule)
  const assignableRoles = ROLES.filter((r) => r !== "owner" || canManageOwners(myRole));
  const canTouch = (m: Member) => manage && (m.role !== "owner" || canManageOwners(myRole));
  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium" });

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

  async function onInvite(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    await run(async () => {
      const res = await api<Invitation & { url: string }>(`/tenants/${tenantId}/invitations`, {
        method: "POST",
        body: { email: form.get("email"), role: form.get("role") },
      });
      setCreated({ email: res.email, url: res.url });
      formEl.reset();
    });
  }

  return (
    <div className="space-y-6">
      {error && <Alert tone="error">{error}</Alert>}

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">{t("members.email")}</th>
                <th className="py-2 pr-4 font-medium">{t("members.role")}</th>
                <th className="py-2 pr-4 font-medium">{t("members.since")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.membership_id} className="border-t border-border">
                  <td className="py-2 pr-4">
                    {m.email}
                    {m.account_id === myAccountId && <span className="text-muted"> ({t("members.you")})</span>}
                  </td>
                  <td className="py-2 pr-4">
                    {canTouch(m) ? (
                      <Select
                        aria-label={t("members.role")}
                        value={m.role}
                        disabled={busy}
                        onChange={(e) =>
                          run(() =>
                            api(`/tenants/${tenantId}/members/${m.membership_id}`, {
                              method: "PATCH",
                              body: { role: e.target.value },
                            }),
                          )
                        }
                      >
                        {assignableRoles.map((r) => (
                          <option key={r} value={r}>
                            {t(`roles.${r}`)}
                          </option>
                        ))}
                      </Select>
                    ) : (
                      t(`roles.${m.role}`)
                    )}
                  </td>
                  <td className="py-2 pr-4 text-muted">{date(m.created_at)}</td>
                  <td className="py-2 text-right">
                    {canTouch(m) && (
                      <Button
                        variant="danger"
                        disabled={busy}
                        onClick={() =>
                          confirm(t("members.removeConfirm", { email: m.email })) &&
                          run(() => api(`/tenants/${tenantId}/members/${m.membership_id}`, { method: "DELETE" }))
                        }
                      >
                        {t("members.remove")}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {manage && (
        <>
          <Card title={t("members.inviteTitle")}>
            <form onSubmit={onInvite} className="flex flex-wrap items-end gap-3">
              <div className="min-w-60 flex-1">
                <Field label={t("members.email")}>
                  <Input name="email" type="email" required />
                </Field>
              </div>
              <Field label={t("members.role")}>
                <Select name="role" defaultValue="viewer">
                  {assignableRoles.map((r) => (
                    <option key={r} value={r}>
                      {t(`roles.${r}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button type="submit" disabled={busy}>
                {t("members.inviteSubmit")}
              </Button>
            </form>
            {created && (
              <div className="mt-4 space-y-2">
                <Alert tone="success">{t("members.linkCreated", { email: created.email })}</Alert>
                <CopyField value={created.url} />
              </div>
            )}
          </Card>

          <Card title={t("members.pending")}>
            {invitations.length === 0 ? (
              <p className="text-sm text-muted">{t("members.noPending")}</p>
            ) : (
              <ul className="space-y-2">
                {invitations.map((i) => (
                  <li key={i.invitation_id} className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="flex-1">
                      {i.email} · {t(`roles.${i.role}`)}
                    </span>
                    <span className="text-muted">{t("members.expires", { date: date(i.expires_at) })}</span>
                    {(i.role !== "owner" || canManageOwners(myRole)) && (
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() =>
                          run(() => api(`/tenants/${tenantId}/invitations/${i.invitation_id}`, { method: "DELETE" }))
                        }
                      >
                        {t("members.revoke")}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
