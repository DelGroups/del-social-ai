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
