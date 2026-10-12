"""Catalogue RBAC : matrice rôles / permissions, séparation des portées, contraintes PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction

from apps.organizations.models import Organization
from apps.users.catalog import PERMISSIONS, PERMISSIONS_BY_CODE, ROLES, validate_catalog
from apps.users.models import Permission, Role, RolePermission, User, UserRole
from apps.users.rbac_sync import sync_rbac_catalog
from conftest import grant_role

# Contraintes de schéma et catalogue : vérifiées avec le rôle propriétaire (hors RLS).
pytestmark = [pytest.mark.django_db, pytest.mark.db_owner]

VIEW = {
    "dashboard.view",
    "map.view",
    "border_posts.view",
    "activities.view",
    "alerts.view",
    "analytics.view",
    "reports.view",
    "settings.view",
}

# Matrice attendue, écrite indépendamment du catalogue à partir du §7.3 et des décisions P9/P10 (ADR 0001).
EXPECTED: dict[tuple[str, str], set[str]] = {
    ("SUPER_ADMIN", "platform"): {
        "platform.organizations",
        "platform.institutional_admins",
        "platform.health",
        "platform.audit",
    },
    ("AUDITOR", "platform"): {"platform.audit"},
    ("ORG_ADMIN", "organization"): VIEW
    | {
        "audit.view",
        "organization.view",
        "users.view",
        "users.manage",
        "activities.create",
        "activities.export",
        "alerts.take",
        "alerts.comment",
        "alerts.assign",
        "alerts.decide",
        "reports.generate",
        "imports.run",
        "border_posts.manage",
        "sources.manage",
        "settings.manage",
    },
    ("SUPERVISOR", "organization"): VIEW
    | {
        "activities.export",
        "alerts.take",
        "alerts.comment",
        "alerts.assign",
        "alerts.decide",
        "analytics.what_if",
        "reports.generate",
    },
    ("AGENT", "organization"): {
        "dashboard.view",
        "map.view",
        "border_posts.view",
        "activities.view",
        "alerts.view",
        "activities.create",
        "alerts.take",
        "alerts.comment",
    },
    ("ANALYST", "organization"): VIEW | {"activities.export", "analytics.what_if", "reports.generate"},
    ("AUDITOR", "organization"): VIEW | {"audit.view", "organization.view", "users.view"},
}


def db_matrix() -> dict[tuple[str, str], set[str]]:
    return {
        (role.code, role.scope): set(role.permissions.values_list("code", flat=True))
        for role in Role.objects.filter(is_system=True)
    }


def test_catalog_is_consistent() -> None:
    validate_catalog()


def test_database_matches_expected_matrix_exactly() -> None:
    """100 % de la matrice : chaque case rôle / permission (§24)."""
    assert db_matrix() == EXPECTED
    assert set(Permission.objects.values_list("code", flat=True)) == {p.code for p in PERMISSIONS}


def test_scope_separation() -> None:
    for (code, scope), permissions in EXPECTED.items():
        scopes = {PERMISSIONS_BY_CODE[p].scope for p in permissions}
        assert scopes == {scope}, code
    # L'Administrateur institutionnel n'a aucun privilège global.
    assert not any(p.startswith("platform.") for p in EXPECTED[("ORG_ADMIN", "organization")])
    # Le Super Administrateur n'a aucun droit opérationnel d'organisme (§7.1).
    assert all(p.startswith("platform.") for p in EXPECTED[("SUPER_ADMIN", "platform")])


def test_auditor_is_strictly_read_only() -> None:
    for scope in ("organization", "platform"):
        role = Role.objects.get(code="AUDITOR", scope=scope)
        codes = set(role.permissions.values_list("code", flat=True))
        assert codes, scope
        assert all(c.endswith(".view") or c == "platform.audit" for c in codes), codes


def test_operational_limits() -> None:
    agent, analyst = EXPECTED[("AGENT", "organization")], EXPECTED[("ANALYST", "organization")]
    assert "imports.run" not in agent  # ADR 0001 · P10
    assert not {"alerts.assign", "alerts.decide", "users.manage"} & agent
    assert (
        not {"alerts.take", "alerts.comment", "alerts.assign", "alerts.decide"} & analyst
    )  # consultation seule
    assert (
        not {"users.manage", "settings.manage", "sources.manage"} & EXPECTED[("SUPERVISOR", "organization")]
    )


def test_mfa_required_for_sensitive_roles() -> None:
    """§9.12 / §19.1 : Super Admin, Admin institutionnel, Superviseur, Auditeur."""
    required = {(r.code, r.scope) for r in Role.objects.filter(is_system=True, mfa_required=True)}
    assert required == {
        ("SUPER_ADMIN", "platform"),
        ("AUDITOR", "platform"),
        ("ORG_ADMIN", "organization"),
        ("SUPERVISOR", "organization"),
        ("AUDITOR", "organization"),
    }


def test_sync_is_idempotent_and_repairs_tampering() -> None:
    agent = Role.objects.get(code="AGENT", scope="organization")
    admin = Role.objects.get(code="ORG_ADMIN", scope="organization")
    RolePermission.objects.create(role=agent, permission=Permission.objects.get(code="users.manage"))
    RolePermission.objects.filter(role=admin, permission__code="users.manage").delete()
    sync_rbac_catalog()
    sync_rbac_catalog()
    assert db_matrix() == EXPECTED
    assert Role.objects.filter(is_system=True).count() == len(ROLES)


# --- Contraintes PostgreSQL (insertion directe, hors ORM) ------------------------------------


def _raw(sql: str, params: list[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def test_db_rejects_platform_permission_in_organization_role() -> None:
    admin = Role.objects.get(code="ORG_ADMIN", scope="organization")
    platform_permission = Permission.objects.get(code="platform.organizations")
    sql = (
        "INSERT INTO users_role_permission (role_id, permission_id, role_scope, permission_scope) "
        "VALUES (%s, %s, %s, %s)"
    )
    # Portées déclarées cohérentes mais fausses : rejet par la clé composite
    # (permission_id, permission_scope).
    with pytest.raises(IntegrityError), transaction.atomic():
        _raw(sql, [admin.pk, platform_permission.pk, "organization", "organization"])
    # Portées réelles mais différentes : rejet par le CHECK role_scope = permission_scope.
    with pytest.raises(IntegrityError), transaction.atomic():
        _raw(sql, [admin.pk, platform_permission.pk, "organization", "platform"])


def test_db_rejects_assignment_to_another_organization(user_a: User, org_b: Organization) -> None:
    agent = Role.objects.get(code="AGENT", scope="organization")
    with pytest.raises(IntegrityError), transaction.atomic():
        UserRole.objects.create(user=user_a, role=agent, scope="organization", organization=org_b)


def test_db_rejects_scope_different_from_role(user_a: User) -> None:
    agent = Role.objects.get(code="AGENT", scope="organization")
    sql = (
        "INSERT INTO users_user_role (user_id, role_id, scope, organization_id, created_at) "
        "VALUES (%s, %s, %s, %s, now())"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        _raw(sql, [user_a.pk, agent.pk, "platform", None])


def test_db_rejects_organization_role_for_platform_account(platform_admin: User, org_a: Organization) -> None:
    agent = Role.objects.get(code="AGENT", scope="organization")
    with pytest.raises(IntegrityError), transaction.atomic():
        UserRole.objects.create(user=platform_admin, role=agent, scope="organization", organization=org_a)


def test_user_cannot_change_organization_while_holding_roles(user_a: User, org_b: Organization) -> None:
    grant_role(user_a, "AGENT")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.filter(pk=user_a.pk).update(organization=org_b)
