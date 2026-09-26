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
  ctas: string[];
  hashtags: { branded: string[]; pool: string[]; max_per_post: number };
  examples: { good: string[]; bad: string[] };
  occasions: string[];
  mention_prices: boolean;
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
