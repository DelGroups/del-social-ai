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
