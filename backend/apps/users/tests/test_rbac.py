"""Évaluation des permissions : refus par défaut, portée, appartenance déduite du serveur."""

from __future__ import annotations

import json
import logging

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.organizations.models import Organization
from apps.organizations.tenancy import TenantContext, context_for_user
from apps.users.models import Role, User, UserRole
from apps.users.rbac import (
    PermissionDeniedError,
    has_permission,
    permission_codes,
    require_permission,
    requires_mfa,
)
from apps.users.selectors import describe_access
from conftest import create_user, grant_role, owner

pytestmark = pytest.mark.django_db

ROLES = ("ORG_ADMIN", "SUPERVISOR", "AGENT", "ANALYST", "AUDITOR")


def make_user(org: Organization, role: str, email: str) -> User:
    user = create_user(email, org)
    grant_role(user, role)
    return user


@pytest.mark.parametrize("role", ROLES)
def test_role_permissions_effective_only_in_own_organization(
    role: str, org_a: Organization, org_b: Organization
) -> None:
    user = make_user(org_a, role, f"{role.lower()}@demo-a.rbi.test")
    own = context_for_user(user)
    codes = permission_codes(user)
    assert codes == set(
        Role.objects.get(code=role, scope="organization").permissions.values_list("code", flat=True)
    )
    for code in codes:
        assert has_permission(user, code, own)
        assert not has_permission(user, code, None)  # pas de contexte : refus
        # Un rôle n'est pas une preuve d'appartenance : contexte d'un autre organisme refusé.
        assert not has_permission(user, code, TenantContext(org_b.pk, "user"))


def test_default_deny(user_a: User, org_a: Organization) -> None:
    """Utilisateur sans rôle, code inconnu, compte inactif, anonyme : tout est refusé."""
    ctx = context_for_user(user_a)
    assert permission_codes(user_a) == frozenset()
    assert not has_permission(user_a, "dashboard.view", ctx)
    grant_role(user_a, "ORG_ADMIN")
    assert not has_permission(user_a, "alerts.delete_everything", ctx)
    assert not has_permission(AnonymousUser(), "dashboard.view", ctx)
    assert not has_permission(None, "dashboard.view", ctx)
    user_a.is_active = False
    with owner():
        user_a.save()
    assert not has_permission(user_a, "users.manage", ctx)
    assert permission_codes(user_a) == frozenset()


def test_platform_permissions_never_apply_to_organizations(platform_admin: User, admin_a: User) -> None:
    ctx_a = context_for_user(admin_a)
    assert has_permission(platform_admin, "platform.organizations")
    assert not has_permission(platform_admin, "platform.organizations", ctx_a)  # jamais dans un contexte
    assert not has_permission(platform_admin, "dashboard.view", ctx_a)  # aucune donnée opérationnelle
    assert not has_permission(platform_admin, "users.manage", ctx_a)
    # L'Administrateur institutionnel n'a aucun privilège global.
    for code in (
        "platform.organizations",
        "platform.institutional_admins",
        "platform.health",
        "platform.audit",
    ):
        assert not has_permission(admin_a, code)
        assert not has_permission(admin_a, code, ctx_a)


def test_inconsistent_platform_row_on_organization_account_is_ignored(admin_a: User) -> None:
    """Affectation SUPER_ADMIN insérée hors services : sans effet pour un compte organisationnel."""
    with owner():
        UserRole.objects.create(user=admin_a, role=Role.objects.get(code="SUPER_ADMIN"), scope="platform")
    assert not has_permission(admin_a, "platform.organizations")
    assert not any(code.startswith("platform.") for code in permission_codes(admin_a))


def test_require_permission_denial_is_generic_and_audited(
    user_a: User, org_a: Organization, caplog: pytest.LogCaptureFixture
) -> None:
    grant_role(user_a, "AGENT")
    caplog.set_level(logging.INFO, logger="rbi.audit")
    with pytest.raises(PermissionDeniedError) as excinfo:
        require_permission(user_a, "users.manage", context_for_user(user_a))
    assert "users.manage" not in str(excinfo.value)
    [event] = [json.loads(r.getMessage()) for r in caplog.records if r.name == "rbi.audit"]
    assert event["action"] == "rbac.check" and event["outcome"] == "denied"
    assert event["details"] == {"permission": "users.manage"}


@pytest.mark.parametrize(
    ("role", "expected"),
    [("ORG_ADMIN", True), ("SUPERVISOR", True), ("AUDITOR", True), ("AGENT", False), ("ANALYST", False)],
)
def test_mfa_requirement_follows_roles(role: str, expected: bool, org_a: Organization) -> None:
    assert requires_mfa(make_user(org_a, role, f"mfa.{role.lower()}@demo-a.rbi.test")) is expected


def test_super_admin_requires_mfa(platform_admin: User, platform_user_without_permission: User) -> None:
    assert requires_mfa(platform_admin)
    assert not requires_mfa(platform_user_without_permission)


def test_describe_access(admin_a: User, org_b: Organization, platform_admin: User) -> None:
    access = describe_access(admin_a, context_for_user(admin_a))
    assert access["roles"] == ["ORG_ADMIN"] and "users.manage" in access["permissions"]
    assert describe_access(admin_a, TenantContext(org_b.pk, "user")) == {"roles": [], "permissions": []}
    assert describe_access(platform_admin, None)["roles"] == ["SUPER_ADMIN"]
