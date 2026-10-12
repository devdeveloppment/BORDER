"""Après authentification : identité reconstruite, RBAC recalculé, contexte d'organisme serveur, aucune
fuite."""

from __future__ import annotations

import io
import sys

import pytest
from django.contrib.auth.backends import ModelBackend
from django.core.management import CommandError, call_command
from django.urls import get_resolver

from apps.authentication.backends import RBIAuthBackend
from apps.organizations.models import Organization
from apps.users.models import Role, User
from conftest import owner

from .support import PASSWORD, Api, enroll, make_member

pytestmark = pytest.mark.django_db


def test_me_reflects_rbac_and_own_organization_only(org_a: Organization, org_b: Organization) -> None:
    analyst = make_member(org_a, "ANALYST", "analyste@demo-a.rbi.test")
    api = Api()
    api.post("/auth/login", {"email": analyst.email, "password": PASSWORD})
    me = api.get(
        f"/me?organization_id={org_b.pk}", headers={"X-Organization-Id": str(org_b.pk)}
    ).json()  # valeurs client ignorées
    assert me["organization"]["id"] == str(org_a.pk)
    expected = set(
        Role.objects.get(code="ANALYST", scope="organization").permissions.values_list("code", flat=True)
    )
    assert set(me["permissions"]) == expected
    assert "users.manage" not in me["permissions"] and not any(
        p.startswith("platform.") for p in me["permissions"]
    )
    assert str(org_b.pk) not in api.get("/me").content.decode()


def test_role_change_is_reflected_immediately(org_a: Organization) -> None:
    from conftest import grant_role

    agent = make_member(org_a, "AGENT", "agent.roles@demo-a.rbi.test")
    api = Api()
    api.post("/auth/login", {"email": agent.email, "password": PASSWORD})
    assert "reports.generate" not in api.get("/me").json()["permissions"]
    grant_role(agent, "ANALYST")  # rôle sans MFA : la session reste ouverte
    assert "reports.generate" in api.get("/me").json()["permissions"]  # recalculé à chaque requête


def test_platform_admin_identity(platform_admin: User) -> None:
    platform_admin.set_password(PASSWORD)
    with owner():
        platform_admin.save()
    api = Api()
    enroll(api, platform_admin)  # SUPER_ADMIN : MFA obligatoire
    me = api.get("/me").json()
    assert me["organization"] is None and me["roles"] == ["SUPER_ADMIN"]
    assert set(me["permissions"]) == {
        "platform.organizations",
        "platform.institutional_admins",
        "platform.health",
        "platform.audit",
    }


def test_backend_grants_no_django_permission(org_a: Organization) -> None:
    admin = make_member(org_a, "ORG_ADMIN", "admin.perm@demo-a.rbi.test")
    backend = RBIAuthBackend()
    assert backend.has_perm(admin, "users.manage") is False
    assert backend.get_all_permissions(admin) == set()
    assert not hasattr(admin, "is_superuser")
    assert issubclass(RBIAuthBackend, ModelBackend)


def test_super_admin_creation_is_not_exposed_over_http() -> None:
    """P2.8 : routes imbriquées comprises. ``/users`` (création d'un compte d'organisme, rôles d'organisme
    seulement) et ``…/institutional-admins`` existent désormais ; aucune route ne vise un Super Administrateur
    ni un compte plateforme (voir aussi apps/core/tests/test_api_routes.py)."""
    from apps.core.tests.api_support import iter_routes

    flat = " ".join(route for route, _ in iter_routes(get_resolver()))
    assert "super" not in flat and "platform/users" not in flat
    assert "api/v1/users" in flat  # l'énumération descend bien dans les routes imbriquées


def test_super_admin_command_enforces_password_policy() -> None:
    stdin, sys.stdin = sys.stdin, io.StringIO("faible\n")
    try:
        with pytest.raises(CommandError):
            call_command(
                "create_super_admin",
                email="sa@plateforme.rbi.test",
                password_stdin=True,
                stdout=io.StringIO(),
            )
    finally:
        sys.stdin = stdin
    with owner():
        assert not User.objects.filter(email="sa@plateforme.rbi.test").exists()


def test_super_admin_command_refuses_existing_email(platform_admin: User) -> None:
    stdin, sys.stdin = sys.stdin, io.StringIO("Mot-de-passe-fictif-2026!\n")
    try:
        with owner(), pytest.raises(CommandError, match="existe déjà"):
            call_command(
                "create_super_admin", email=platform_admin.email, password_stdin=True, stdout=io.StringIO()
            )
    finally:
        sys.stdin = stdin
    with owner():
        assert User.objects.filter(email=platform_admin.email).count() == 1
