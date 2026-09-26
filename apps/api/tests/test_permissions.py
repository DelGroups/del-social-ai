"""Role → permission table. Pure: no database needed."""
import pytest

from del_social.models import MemberRole
from del_social.tenants.permissions import ROLE_PERMISSIONS, Permission, has_permission

P = Permission

EXPECTED = {
    MemberRole.VIEWER: {P.VIEW},
    MemberRole.APPROVER: {P.VIEW, P.APPROVE_CONTENT},
    MemberRole.ADMIN: {P.VIEW, P.APPROVE_CONTENT, P.MANAGE_CONNECTIONS, P.MANAGE_BRAND, P.MANAGE_MEDIA, P.MANAGE_MEMBERS, P.VIEW_USAGE},
    MemberRole.OWNER: set(Permission),
}


@pytest.mark.parametrize("role", list(MemberRole))
def test_role_permissions_match_spec(role):
    assert set(ROLE_PERMISSIONS[role]) == EXPECTED[role]
    for permission in Permission:
        assert has_permission(role, permission) == (permission in EXPECTED[role])


def test_roles_are_strictly_ordered():
    order = [MemberRole.VIEWER, MemberRole.APPROVER, MemberRole.ADMIN, MemberRole.OWNER]
    for lower, higher in zip(order, order[1:]):
        assert ROLE_PERMISSIONS[lower] < ROLE_PERMISSIONS[higher]


def test_only_owners_manage_owners_and_tenant():
    for role in MemberRole:
        expected = role is MemberRole.OWNER
        assert has_permission(role, P.MANAGE_OWNERS) is expected
        assert has_permission(role, P.MANAGE_TENANT) is expected
