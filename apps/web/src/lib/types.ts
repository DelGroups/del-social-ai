export type Role = "owner" | "admin" | "approver" | "viewer";
export const ROLES: Role[] = ["owner", "admin", "approver", "viewer"];

export type Membership = { tenant_id: string; tenant_name: string; role: Role };

export type Me = {
  account_id: string;
  email: string;
  is_platform_admin: boolean;
  memberships: Membership[];
};

export type Member = {
  membership_id: string;
  account_id: string;
  email: string;
  role: Role;
  created_at: string;
};

export type Invitation = {
  invitation_id: string;
  email: string;
  role: Role;
  created_at: string;
  expires_at: string;
};

export type InvitationInfo = {
  tenant_name: string;
  email: string;
  role: Role;
  status: "pending" | "expired" | "accepted" | "revoked";
};

// Mirrors apps/api/del_social/tenants/permissions.py (the API enforces it; this only hides buttons)
export const canManageMembers = (role: Role) => role === "owner" || role === "admin";
export const canManageOwners = (role: Role) => role === "owner";

export type ChannelName = "instagram" | "facebook" | "telegram" | "whatsapp" | "tiktok" | "youtube";

export type Connection = {
  connection_id: string;
  channel: ChannelName;
  external_id: string;
  display_name: string;
  status: "active" | "error";
  token_expires_at: string | null;
  last_checked_at: string | null;
  last_error: string | null;
  details: Record<string, string>;
  created_at: string;
};

export type ChannelInfo = {
  channel: ChannelName;
  connect_method: "oauth" | "bot_token" | "embedded_signup";
  available: boolean;
  configured: boolean;
  capabilities: Record<string, boolean>;
  connections: Connection[];
};

export type PageOption = {
  page_id: string;
  name: string;
  instagram_id: string | null;
  instagram_username: string | null;
};

export const canManageConnections = (role: Role) => role === "owner" || role === "admin";

// Mirrors apps/api/del_social/knowledge/brand_profile.py (the API validates it)
export type BrandProfileData = {
  basics: Record<string, string | string[]>;
  audience: { description: string; segments: string[] };
  products: { categories: string[]; materials: string[]; usps: string[] };
  voice: { tone_words: string[]; formality: string; emoji: string; caption_length: string; notes: string };
  languages: { mode: string };
  never: { words: string[]; topics: string[]; competitors: string[] };
  claims: string[];
  terminology: string[];
  ctas: string[];
  hashtags: { branded: string[]; pool: string[]; max_per_post: number };
  examples: { good: string[]; bad: string[] };
  occasions: string[];
  image_editing: Record<"background" | "remove_objects" | "enhance" | "recolor" | "swap_product", boolean>;
  mention_prices: boolean;
  market?: {
    competitors_instagram: string[];
    watch_sites: string[];
    keywords: string[];
    notes: string;
    report_language: "az" | "ru" | "en" | "fa";
    daily_research: boolean;
    daily_briefing: boolean;
  };
};

export type BrandProfileOut = {
  version: number;
  data: BrandProfileData;
  created_at: string | null;
  created_by_email: string | null;
};

export const canManageBrand = (role: Role) => role === "owner" || role === "admin";

export type AgentUsage = {
  agent: string;
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
};

export type Usage = { month: string; calls: number; cost_usd: string; by_agent: AgentUsage[] };

export const canViewUsage = (role: Role) => role === "owner" || role === "admin";

export type EvalRating = "publishable" | "needs_edit" | "wrong";

export type EvalOption = {
  angle: string;
  caption: string;
  caption_az: string;
  caption_ru: string;
  hashtags: string[];
  alt_text: string;
  verdict: "pass" | "fix" | "block";
  findings: { source: string; code: string; severity: "fix" | "block"; message: string }[];
};

export type EvalItem = {
  item_id: string;
  position: number;
  brief: Record<string, unknown>;
  result: { options: EvalOption[]; passed: number; revisions: number; question: string | null; cost_usd: string } | null;
  error: string | null;
  ratings: Record<string, EvalRating>;
  note: string | null;
  rated_at: string | null;
};

export type EvalRunSummary = {
  run_id: string;
  suite: "copywriter" | "brand_guardian";
  status: "running" | "done" | "failed";
  brand_version: number;
  prompt_refs: Record<string, string>;
  briefs_total: number;
  completed: number;
  failed: number;
  rated: number;
  successes: number;
  success_rate: number | null;
  target: number;
  cost_usd: string;
  created_at: string;
  finished_at: string | null;
};

export type EvalRunDetail = EvalRunSummary & { items: EvalItem[] };

// Mirrors Permission.APPROVE_CONTENT
export const canApprove = (role: Role) => role !== "viewer";

export type MediaSource = "own" | "render" | "licensed" | "reference";
export type EditKind = "enhance" | "remove" | "background" | "recolor" | "swap";
export type RecipeStep = { on: boolean; request: string; reference_asset_id: string | null };
export type Recipe = {
  subject: string;
  enhance: boolean;
  remove: RecipeStep;
  background: RecipeStep;
  recolor: RecipeStep;
  swap: RecipeStep;
};

export type MediaAsset = {
  asset_id: string;
  kind: "photo" | "logo";
  filename: string;
  width: number;
  height: number;
  bytes: number;
  tags: string[];
  description: string;
  focal_x: number;
  focal_y: number;
  enhance: boolean;
  source: MediaSource;
  parent_asset_id: string | null;
  status: "pending" | "ready" | "failed";
  edit: { kinds: EditKind[]; recipe?: Recipe; error?: string; cost_usd?: string | null; cost_complete?: boolean } | null;
  approved_at: string | null;
  recipe: Recipe | null;
  product_id: string | null;
  position: number;
  default_logo: boolean;
  analysis: PhotoAnalysis | null;
  publishable: boolean;
  created_at: string;
  urls: Record<string, string>; // signed, ~24h: thumb, feed, square, feed-logo, square-logo
};

// Mirrors Permission.MANAGE_MEDIA
export const canManageMedia = (role: Role) => role === "owner" || role === "admin";

export type ProductInfo = {
  product_id: string;
  name: string;
  category: string;
  description: string;
  photos: number;
  created_at: string;
};

export type PhotoAnalysis = {
  status: "queued" | "running" | "done" | "failed";
  error?: string;
  looks_like?: "render" | "photo" | "unclear";
  title_az?: string;
  category?: string;
  room?: string | null;
  style?: string[];
  colors?: string[];
  materials_visible?: string[];
  features?: string[];
  hashtags?: string[];
  best_format?: "feed" | "square" | "landscape";
  quality_issues?: string[];
  suggested_edits?: string[];
  product_action?: "created" | "joined" | null;
  human_fields?: string[];
  cost_usd?: string | null;
};

export type PostOption = {
  angle: string;
  caption: string;
  caption_az: string;
  caption_ru: string;
  hashtags: string[];
  verdict: "pass" | "fix" | "block";
  findings: { source: string; code: string; severity: string; message: string }[];
};

export type PostInfo = {
  post_id: string;
  status: "generating" | "ready" | "failed" | "approved" | "publishing" | "published" | "partly_published" | "scheduled";
  product_id: string | null;
  format: "feed" | "square" | "landscape";
  with_logo: boolean;
  channels: string[];
  notes: string;
  photos: { asset_id: string; url: string }[];
  options: PostOption[];
  question: string | null;
  chosen_option: number | null;
  caption: string | null;
  error: string | null;
  results: Record<string, { id?: string; url?: string; error?: string; account?: string }>;
  cost_usd: string | null;
  approved_at: string | null;
  published_at: string | null;
  scheduled_at: string | null;
  task_id: string | null;
  created_at: string;
};

export type TaskInfo = {
  task_id: string;
  title: string;
  kind: "post" | "market" | "briefing";
  status: "running" | "waiting_approval" | "scheduled" | "done" | "failed" | "cancelled";
  steps: { key: string; agent: string | null; status: "pending" | "running" | "done" | "waiting" | "failed"; note?: string }[];
  post_id: string | null;
  created_at: string;
};

export type LiveJob = TaskInfo & {
  thumb_url: string | null;
  post_status: PostInfo["status"] | null;
  scheduled_at: string | null;
  updated_at: string;
};

export type ChatMsg = {
  message_id: string;
  role: "user" | "agent";
  agent: string | null;
  text: string;
  created_at: string;
  task: TaskInfo | null;
  post: PostInfo | null;
  payload: CardPayload | null;
};

export type LiveInfo = {
  agents: { agent: string; state: "working" | "idle"; activity: string | null; last_at: string | null; done_today: number }[];
  running: TaskInfo[];
  jobs: LiveJob[];
  waiting: PostInfo[];
  scheduled: PostInfo[];
  published: PostInfo[];
  events: { agent: string; kind: string; title: string; at: string }[];
  photos_total: number;
  photos_unanalysed: number;
  connections: { channel: string; name: string; status: string }[];
  now: string;
};

// Packages (ADR 007): allowances and credits, never the AI cost in dollars
export type PlanInfo = {
  plan_id: string;
  name: string;
  price_azn: string;
  posts_per_month: number | null; // null = unlimited
  channels: number | null;
  users: number | null;
  video_credits: number | null;
  features: Record<string, boolean>;
};

export type Meter = { used: number; limit: number | null };

export type PlanStatus = {
  state: "none" | "expired" | "limit" | "warning" | "ok";
  plan: PlanInfo | null;
  starts_at: string | null;
  expires_at: string | null;
  period_start: string | null;
  period_end: string | null;
  posts: Meter;
  posts_published: number;
  posts_scheduled: number;
  drafts: Meter;
  channels: Meter;
  users: Meter;
  video: Meter;
  catalog: PlanInfo[];
  open_request: { plan_id: string; created_at: string } | null;
};

export const canBuyPlan = (role: Role) => role === "owner";

export type TenantOverview = {
  tenant_id: string;
  name: string;
  created_at: string;
  plan_id: string | null;
  price_azn: string | null;
  starts_at: string | null;
  expires_at: string | null;
  extra_video_credits: number | null;
  period_start: string | null;
  period_end: string | null;
  posts_published: number;
  posts_scheduled: number;
  posts_limit: number | null;
  members: number;
  channels: number;
  ai_cost_month_usd: string;
  margin_month_usd: string | null;
  open_request_plan: string | null;
  open_request_at: string | null;
};

// Daily work (ADR 008): market research and the Team Lead's morning report
export type Finding = { title: string; detail: string; evidence: string; confidence: "low" | "medium" | "high" };
export type PostIdea = { product_id: string | null; product_name: string; angle: string; why: string; format: string };
export type MarketReportData = {
  headline: string;
  summary: string;
  demand: Finding[];
  colors_materials: Finding[];
  competitors: Finding[];
  customer_voice: Finding[];
  opportunities: Finding[];
  post_ideas: PostIdea[];
  questions: string[];
  data_gaps: string[];
};
export type SuggestionData = {
  title: string;
  why: string;
  action: "create_post" | "none";
  product_id: string | null;
  when: string | null;
  notes: string | null;
  status: "open" | "started";
  post_id?: string;
};
export type BriefingData = {
  greeting: string;
  yesterday: string;
  market: string;
  today_plan: string[];
  suggestions: SuggestionData[];
  questions: string[];
};
export type CardPayload =
  | { type: "market"; report_id: string; headline: string; ideas: number; questions: string[] }
  | { type: "briefing"; report_id: string; briefing: BriefingData; market_report_id: string | null };

export type AccountStats = {
  posts_last_7_days: number;
  posts_last_30_days: number;
  avg_likes: number;
  avg_comments: number;
  engagement_rate_percent: number | null;
  post_types: Record<string, number>;
};
export type CollectedAccount = {
  username?: string;
  entry?: string;
  name?: string;
  followers?: number | null;
  error?: string;
  stats?: AccountStats;
  top_posts?: { date: string; likes: number; comments: number; caption: string; permalink: string | null; type: string }[];
  recent_customer_comments?: { date: string; on_post: string; text: string }[];
};
export type DailyRow = {
  report_id: string;
  kind: "market" | "briefing";
  day: string;
  status: "running" | "done" | "failed";
  headline: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};
export type DailyFull = DailyRow & {
  input: { own?: CollectedAccount | null; competitors?: CollectedAccount[]; facts?: Record<string, unknown> };
  output: (MarketReportData | BriefingData) | null;
  sources: { title: string; url: string }[];
};
