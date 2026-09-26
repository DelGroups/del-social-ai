import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { SignOutButton } from "@/components/client";
import { AuthFrame } from "@/components/shell";
import { Alert } from "@/components/ui";
import { apiGet, getMe } from "@/lib/server-api";
import type { InvitationInfo } from "@/lib/types";

import { AcceptForm } from "./accept-form";

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const t = await getTranslations();
  const { data: invitation } = await apiGet<InvitationInfo>(`/auth/invitations/${encodeURIComponent(token)}`);

  if (!invitation) {
    return (
      <AuthFrame title={t("invite.title")}>
        <Alert tone="error">{t("invite.notFound")}</Alert>
      </AuthFrame>
    );
  }
  if (invitation.status !== "pending") {
    return (
      <AuthFrame title={t("invite.title")}>
        <Alert tone="error">{t(`invite.${invitation.status}`)}</Alert>
      </AuthFrame>
    );
  }

  const me = await getMe();
  const role = t(`roles.${invitation.role}`);
  return (
    <AuthFrame title={t("invite.title")}>
      <p>{t("invite.joinAs", { tenant: invitation.tenant_name, role })}</p>
      <p className="text-sm text-muted">{t("invite.forEmail", { email: invitation.email })}</p>
      {me && me.email !== invitation.email ? (
        <>
          <Alert tone="error">
            {t("invite.signedInAs", { email: me.email })} {t("invite.wrongAccount")}
          </Alert>
          <SignOutButton />
        </>
      ) : (
        <AcceptForm token={token} signedIn={Boolean(me)} />
      )}
      {!me && (
        <p className="text-xs text-muted">
          <Link href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`} className="underline">
            {t("invite.signInToAccept")}
          </Link>
        </p>
      )}
    </AuthFrame>
  );
}
