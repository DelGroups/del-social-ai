// YouTube Studio: the shapes the API returns (routes/youtube.py) and small helpers.
export type YtReport = {
  report_id: string;
  kind: "pulse" | "daily" | "review" | "ideas";
  status: "running" | "done" | "failed";
  output: Record<string, any> | null;
  input: Record<string, any>;
  sources: { title: string; url: string }[];
  credits: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export type YtSettings = {
  about: string;
  audience: string;
  tone: string;
  languages: ("az" | "ru" | "en" | "tr")[];
  region: string;
  pulse_hours: 0 | 3 | 6 | 12;
  daily_report: boolean;
  daily_at: number;
  report_language: "auto" | "az" | "ru" | "en" | "fa";
  links: string;
  competitors: string[];
  reply_mode: YtReplyMode;
};

export type YtReplyMode = "manual" | "approval" | "auto";

export type YtDashboard = {
  addon: { active: boolean; total: number; monthly_left: number; purchased: number; period_end: string | null; costs: Record<string, number> };
  google_configured: boolean;
  connection: { connection_id: string; name: string; status: string; last_error: string | null; handle: string | null; avatar: string | null; country: string | null } | null;
  channel?: {
    subscribers: number | null;
    views: number | null;
    videos: number | null;
    growth_7d: number | null;
    growth_30d: number | null;
    series: { day: string; subscribers: number | null; views: number | null }[];
  };
  settings?: YtSettings;
  latest?: Record<"pulse" | "daily" | "review" | "ideas", YtReport | null>;
  counts?: { videos: number; replies_waiting: number; ideas_new: number };
};

export type YtVideo = {
  video_id: string;
  title: string;
  description: string;
  tags: string[];
  published_at: string | null;
  duration_s: number | null;
  privacy: string | null;
  publish_at: string | null;
  is_short: boolean;
  thumbnail_url: string | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  has_captions: boolean;
  kit?: string | null;
  thumbnail_applied?: boolean;
};

export type ThumbSpec = {
  text: string;
  language: "az" | "ru" | "en" | "tr";
  emphasis: string;
  layout: string;
  palette: string;
  font: string;
  size: "m" | "l" | "xl";
  uppercase: boolean;
  outline: boolean;
  shadow: boolean;
  glow: boolean;
  darken: number;
  blur: number;
  saturation: number;
  brightness: number;
  subject: "none" | "left" | "right" | "center";
  subject_scale: number;
  subject_outline: boolean;
  badge: string;
  arrow: "none" | "left" | "right";
  frame: boolean;
};

export type YtThumb = {
  thumbnail_id: string;
  video_id: string | null;
  status: "working" | "ready" | "applied" | "failed";
  spec: ThumbSpec;
  background: { source?: string; prompt?: string; concept?: { why?: string } };
  error: string | null;
  applied_at: string | null;
  created_at: string;
  rev: number;
  image: string;
};

export type YtDraft = {
  draft_id: string;
  video_id: string;
  status: "running" | "ready" | "applied" | "failed";
  options: Record<string, unknown>;
  output: {
    titles: { text: string; style: string; why: string }[];
    tags: string[];
    hashtags: string[];
    pinned_comment: string;
    chapters_timed: { time: string; title: string }[];
    translations: { language: string; title: string; description: string }[];
    thumbnail_texts: string[];
    final_description: string;
    segments: number;
  } | null;
  chosen: {
    title: string;
    description: string;
    tags: string[];
    translations: { language: string; title: string; description: string }[];
    language: string;
    comment: string;
  } | null;
  seo: { checks: Record<string, boolean>; score: number; main_keyword: string | null; title_lengths: number[] } | null;
  error: string | null;
  applied_at: string | null;
  created_at: string;
};

export type YtIdea = {
  idea_id: string;
  title: string;
  status: "new" | "saved" | "used" | "dismissed";
  angle: string;
  hook: string;
  format: "long" | "short" | "series";
  why: string;
  evidence: string;
  thumbnail: string;
  keywords: string[];
  difficulty: "easy" | "medium" | "hard";
  created_at: string;
};

export type YtComment = {
  reply_id: string;
  comment_id: string;
  video_id: string | null;
  video_title: string;
  author: string;
  text: string;
  published_at: string | null;
  draft: string;
  status: "new" | "drafted" | "sent" | "dismissed";
  sent_at: string | null;
  sent_by: "person" | "agent" | null;
  hold: "check" | "link" | "old" | "limit" | "error" | null;
};

export type YtCompetitor = {
  competitor_id: string;
  channel_id: string;
  handle: string | null;
  title: string;
  subscribers: number | null;
  videos: number | null;
  views: number | null;
  avatar: string | null;
  source: string;
};

export const LAYOUTS = ["left_text", "right_text", "center_big", "top_banner", "bottom_bar", "split", "corner_badge", "minimal"] as const;
export const PALETTES: Record<string, [string, string, string]> = {
  // text, emphasis, band (same values as the API's render.PALETTE)
  red_white: ["#FFFFFF", "#FF2D2D", "#E00000"],
  yellow_black: ["#FFFFFF", "#FFD400", "#FFD400"],
  neon: ["#FFFFFF", "#39FF14", "#7B2FF7"],
  clean_white: ["#111111", "#E4002B", "#FFFFFF"],
  dark_gold: ["#FFFFFF", "#F5C542", "#B8860B"],
  blue_orange: ["#FFFFFF", "#FF8A00", "#1463FF"],
  pastel: ["#2B2B3A", "#FF5C8A", "#FFD6E0"],
  green_black: ["#FFFFFF", "#00E676", "#00C853"],
};
export const FONTS = ["bold", "condensed", "wide", "tech", "elegant", "rounded"] as const;

export function duration(s: number | null): string {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}
