"""Gestion des utilisateurs : cloisonnement, élévation de privilèges, dernier administrateur, plateforme."""

from __future__ import annotations

import io
import uuid

import pytest
from django.core.management import call_command

from apps.organizations.exceptions import InvalidTransition, PlatformAccessDenied
from apps.organizations.models import Organization
from apps.organizations.platform import platform_scope
from apps.organizations.tenancy import TenantContext, context_for_user
from apps.users import selectors, services
from apps.users.models import User, UserRole
from apps.users.rbac import PermissionDeniedError, has_permission, permission_codes
from conftest import OrganizationFactory, create_user, grant_role, owner

pytestmark = pytest.mark.django_db


def roles_of(user: User) -> set[str]:
    with owner():
        return set(UserRole.objects.filter(user=user).values_list("role__code", flat=True))


# --- Création de comptes ----------------------------------------------------------------------


def test_admin_creates_user_in_own_organization_only(admin_a: User, org_a: Organization) -> None:
    created = services.create_organization_user(
        admin_a, context_for_user(admin_a), email="nouvel.agent@demo-a.rbi.test", roles=("AGENT",)
    )
    assert (
        created.organization_id == org_a.pk
    )  # issu du contexte serveur : aucun paramètre d'organisme n'existe
    assert roles_of(created) == {"AGENT"}
    assert not created.has_usable_password()  # invitation sécurisée : P2.5


@pytest.mark.parametrize("role", ["SUPERVISOR", "AGENT", "ANALYST", "AUDITOR"])
def test_non_admin_roles_cannot_manage_users(role: str, org_a: Organization, user_b: User) -> None:
    actor = create_user(f"{role.lower()}@demo-a.rbi.test", org_a)
    grant_role(actor, role)
    target = create_user("cible@demo-a.rbi.test", org_a)
    ctx = context_for_user(actor)
    count = User.objects.count()
    with pytest.raises(PermissionDeniedError):
        services.create_organization_user(actor, ctx, email="x@demo-a.rbi.test")
    with pytest.raises(PermissionDeniedError):
        services.assign_role(actor, ctx, target.pk, "ORG_ADMIN")
    with pytest.raises(PermissionDeniedError):
        services.set_user_active(actor, ctx, target.pk, active=False)
    assert User.objects.count() == count
    assert roles_of(target) == set()


def test_platform_role_codes_cannot_be_granted_by_institutional_admin(admin_a: User, user_a: User) -> None:
    ctx = context_for_user(admin_a)
    with pytest.raises(PermissionDeniedError):
        services.assign_role(admin_a, ctx, user_a.pk, "SUPER_ADMIN")
    count = User.objects.count()
    with pytest.raises(PermissionDeniedError):
        services.create_organization_user(
            admin_a, ctx, email="pirate@demo-a.rbi.test", roles=("SUPER_ADMIN",)
        )
    assert User.objects.count() == count  # rien de créé (transaction annulée)
    # « AUDITOR » demandé par un Admin institutionnel désigne toujours l'auditeur d'ORGANISME.
    services.assign_role(admin_a, ctx, user_a.pk, "AUDITOR")
    assert not has_permission(user_a, "platform.audit")


# --- Cloisonnement inter-organismes -----------------------------------------------------------


def test_admin_cannot_touch_users_of_another_organization(admin_a: User, user_b: User) -> None:
    ctx = context_for_user(admin_a)
    with pytest.raises(User.DoesNotExist) as foreign:
        services.assign_role(admin_a, ctx, user_b.pk, "AGENT")
    with pytest.raises(User.DoesNotExist) as unknown:
        services.assign_role(admin_a, ctx, uuid.uuid4(), "AGENT")
    assert str(foreign.value) == str(unknown.value)  # indiscernable d'un identifiant inexistant
    with pytest.raises(User.DoesNotExist):
        services.set_user_active(admin_a, ctx, user_b.pk, active=False)
    with pytest.raises(User.DoesNotExist):
        services.revoke_role(admin_a, ctx, user_b.pk, "AGENT")
    with owner():
        user_b.refresh_from_db()
    assert user_b.is_active and roles_of(user_b) == set()


def test_forged_context_of_another_organization_is_refused(admin_a: User, org_b: Organization) -> None:
    """Un contexte d'un autre organisme (organization_id manipulé) ne donne aucun droit, même à un admin."""
    forged = TenantContext(org_b.pk, "user")
    with pytest.raises(PermissionDeniedError):
        services.create_organization_user(admin_a, forged, email="infiltre@demo-b.rbi.test")
    with owner():
        assert not User.objects.filter(email="infiltre@demo-b.rbi.test").exists()


def test_user_listing_limited_to_own_organization(
    admin_a: User, user_a: User, user_b: User, org_a: Organization, platform_admin: User
) -> None:
    auditor = create_user("auditeur@demo-a.rbi.test", org_a)
    grant_role(auditor, "AUDITOR")
    for reader in (admin_a, auditor):
        emails = {u.email for u in selectors.list_organization_users(reader, context_for_user(reader))}
        assert emails == {"admin@demo-a.rbi.test", "agent@demo-a.rbi.test", "auditeur@demo-a.rbi.test"}
    grant_role(user_a, "AGENT")
    with pytest.raises(PermissionDeniedError):
        selectors.list_organization_users(user_a, context_for_user(user_a))
    with pytest.raises(PermissionDeniedError):
        selectors.list_organization_users(platform_admin, TenantContext(org_a.pk, "user"))


# --- Élévation de privilèges et auto-administration ------------------------------------------


def test_no_self_assignment_nor_self_deactivation(admin_a: User) -> None:
    ctx = context_for_user(admin_a)
    with pytest.raises(services.SelfManagementError):
        services.assign_role(admin_a, ctx, admin_a.pk, "AUDITOR")
    with pytest.raises(services.SelfManagementError):
        services.set_user_active(admin_a, ctx, admin_a.pk, active=False)
    assert roles_of(admin_a) == {"ORG_ADMIN"}


def test_last_institutional_admin_is_protected(admin_a: User, org_a: Organization) -> None:
    ctx = context_for_user(admin_a)
    second = services.create_organization_user(
        admin_a, ctx, email="admin2@demo-a.rbi.test", roles=("ORG_ADMIN",)
    )
    services.set_user_active(admin_a, ctx, second.pk, active=False)  # 2 → 1 administrateur actif : permis
    with pytest.raises(services.LastAdministratorError):
        services.revoke_role(admin_a, ctx, admin_a.pk, "ORG_ADMIN")  # dernier administrateur actif
    assert roles_of(admin_a) == {"ORG_ADMIN"}
    services.set_user_active(admin_a, ctx, second.pk, active=True)
    services.revoke_role(admin_a, ctx, admin_a.pk, "ORG_ADMIN")  # un autre administrateur actif existe
    assert roles_of(admin_a) == set()


def test_deactivated_user_loses_every_permission(admin_a: User, org_a: Organization) -> None:
    ctx = context_for_user(admin_a)
    agent = services.create_organization_user(admin_a, ctx, email="agent2@demo-a.rbi.test", roles=("AGENT",))
    assert permission_codes(agent)
    services.set_user_active(admin_a, ctx, agent.pk, active=False)
    with owner():
        agent.refresh_from_db()
    assert permission_codes(agent) == frozenset()


# --- Niveau plateforme -----------------------------------------------------------------------


def test_super_admin_designates_first_institutional_admin(
    platform_admin: User, make_organization: OrganizationFactory
) -> None:
    org = make_organization(status=Organization.Status.AUTORISEE)
    scope = platform_scope(platform_admin, purpose="tests", permission="platform.institutional_admins")
    admin = services.create_institutional_admin(scope, org, email="premier.admin@demo-x.rbi.test")
    assert admin.organization_id == org.pk and roles_of(admin) == {"ORG_ADMIN"}
    assert not admin.has_usable_password()


def test_institutional_admin_designation_requires_the_right_scope(
    platform_admin: User, admin_a: User, make_organization: OrganizationFactory
) -> None:
    org = make_organization(status=Organization.Status.AUTORISEE)
    wrong = platform_scope(platform_admin, purpose="tests")  # délivré pour platform.organizations
    with pytest.raises(PlatformAccessDenied):
        services.create_institutional_admin(wrong, org, email="x@demo-x.rbi.test")
    with pytest.raises(PlatformAccessDenied):
        platform_scope(admin_a, purpose="tentative", permission="platform.institutional_admins")
    with pytest.raises(PlatformAccessDenied):
        services.create_institutional_admin(admin_a, org, email="x@demo-x.rbi.test")  # type: ignore[arg-type]
    with owner():
        assert not User.objects.filter(email="x@demo-x.rbi.test").exists()


@pytest.mark.parametrize("status", ["EN_ATTENTE", "SUSPENDUE", "ARCHIVEE"])
def test_institutional_admin_designation_requires_authorized_organization(
    status: str, platform_admin: User, make_organization: OrganizationFactory
) -> None:
    org = make_organization(status=status)
    scope = platform_scope(platform_admin, purpose="tests", permission="platform.institutional_admins")
    with pytest.raises(InvalidTransition):
        services.create_institutional_admin(scope, org, email="x@demo-x.rbi.test")


def test_create_super_admin_command() -> None:
    """Commande de maintenance : exécutée avec le rôle propriétaire (service migrate)."""
    import sys

    stdin, sys.stdin = sys.stdin, io.StringIO("Mot-de-passe-fictif-2026!\n")
    try:
        out = io.StringIO()
        with owner():
            call_command("create_super_admin", email="Plateforme@RBI.test", password_stdin=True, stdout=out)
    finally:
        sys.stdin = stdin
    with owner():
        user = User.objects.get(email="plateforme@rbi.test")
    assert user.organization_id is None
    assert roles_of(user) == {"SUPER_ADMIN"}
    assert has_permission(user, "platform.organizations")
    assert "Mot-de-passe" not in out.getvalue()


def test_super_admin_bootstrap_refused_with_application_role() -> None:
    """Avec le rôle applicatif (API, worker), la création d'un Super Administrateur est refusée (P2.6)."""
    from apps.core.maintenance import MaintenanceRoleRequired

    with pytest.raises(MaintenanceRoleRequired):
        services.bootstrap_super_admin(
            email="intrus@plateforme.rbi.test", password="Mot-de-passe-fictif-2026!"
        )
    with owner():
        assert not User.objects.filter(email="intrus@plateforme.rbi.test").exists()
