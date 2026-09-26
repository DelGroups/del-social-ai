"""What each tenant role may do. The single place to change it (ADR 002)."""
import enum

from del_social.models import MemberRole


class Permission(enum.StrEnum):
    VIEW = "view"
    APPROVE_CONTENT = "approve_content"
    MANAGE_CONNECTIONS = "manage_connections"
    VIEW_USAGE = "view_usage"  # AI usage and cost
    MANAGE_BRAND = "manage_brand"  # brand profile (what the agents know about the company)
    MANAGE_MEMBERS = "manage_members"  # invite/remove admins, approvers, viewers
    MANAGE_OWNERS = "manage_owners"  # invite/remove/promote owners
    MANAGE_TENANT = "manage_tenant"  # tenant settings, billing, deletion


_VIEWER = frozenset({Permission.VIEW})
_APPROVER = _VIEWER | {Permission.APPROVE_CONTENT}
_ADMIN = _APPROVER | {Permission.MANAGE_CONNECTIONS, Permission.MANAGE_BRAND, Permission.MANAGE_MEMBERS, Permission.VIEW_USAGE}
_OWNER = frozenset(Permission)

ROLE_PERMISSIONS: dict[MemberRole, frozenset[Permission]] = {
    MemberRole.VIEWER: _VIEWER,
    MemberRole.APPROVER: _APPROVER,
    MemberRole.ADMIN: _ADMIN,
    MemberRole.OWNER: _OWNER,
}


def has_permission(role: MemberRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
