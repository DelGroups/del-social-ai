import { useTranslations } from "next-intl";

const STYLE: Record<string, string> = {
  generating: "border-accent text-accent",
  publishing: "border-accent text-accent",
  ready: "border-border text-text",
  approved: "border-border text-text",
  published: "border-success text-success",
  partly_published: "border-danger text-danger",
  failed: "border-danger text-danger",
};

export function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("posts");
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${STYLE[status] ?? "border-border"}`}>{t(`status.${status}`)}</span>;
}
