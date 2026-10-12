"""API des comptes et rôles (P2.8) : contrat P1, permissions, isolation entre organismes, audit."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AuditLog
from apps.core.tests.api_support import signed_in
from apps.organizations.models import Organization
from apps.users.models import User, UserRole
from conftest import create_user, grant_role, owner

pytestmark = pytest.mark.django_db

P1_ORG_USER = {
    "id",
    "email",
    "first_name",
    "last_name",
    "roles",
    "is_active",
    "mfa_enabled",
    "last_login",
    "assigned_posts",
}
SECRETS = ("password", "argon2", "security_stamp", "secret", "bin_key")


@pytest.fixture
def auditor_a(org_a: Organization) -> User:
    user = create_user("auditeur@demo-a.rbi.test", org_a)
    grant_role(user, "AUDITOR")
    return user


def test_list_is_limited_to_own_organization_and_follows_p1_contract(
    admin_a: User, user_a: User, user_b: User, org_b: Organization
) -> None:
    with owner():
        TOTPDevice.objects.create(user=user_a, name="totp", confirmed=True)
        TOTPDevice.objects.create(user=user_b, name="totp", confirmed=True)
    response = signed_in(admin_a).get(
        f"/users?organization_id={org_b.pk}", headers={"X-Organization-Id": str(org_b.pk)}
    )
    assert response.status_code == 200
    rows = response.json()
    assert {row["email"] for row in rows} == {admin_a.email, user_a.email}
    assert all(set(row) == P1_ORG_USER for row in rows)
    by_email = {row["email"]: row for row in rows}
    assert by_email[user_a.email]["mfa_enabled"] is True and by_email[admin_a.email]["mfa_enabled"] is False
    assert by_email[admin_a.email]["roles"] == ["ORG_ADMIN"]
    body = response.content.decode().lower()
    assert all(word not in body for word in SECRETS)
    assert str(user_b.pk) not in body


def test_auditor_reads_but_cannot_write(auditor_a: User, user_a: User) -> None:
    api = signed_in(auditor_a)
    assert api.get("/users").status_code == 200
    assert api.get(f"/users/{user_a.pk}").status_code == 200
    assert api.post("/users", {"email": "x@demo-a.rbi.test"}).status_code == 403
    assert api.patch(f"/users/{user_a.pk}", {"is_active": False}).status_code == 403


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PATCH", "", {"is_active": False}),
        ("POST", "/roles", {"role": "ANALYST"}),
        ("DELETE", "/roles/AGENT", None),
        ("POST", "/mfa-reset", {}),
    ],
)
def test_other_organization_account_is_indistinguishable_from_unknown(
    admin_a: User, user_b: User, method: str, suffix: str, body: Any
) -> None:
    """Identifiant d'un compte de B dans l'URL : 404, comme un identifiant inexistant ; rien n'est modifié."""
    grant_role(user_b, "AGENT")
    api = signed_in(admin_a)
    foreign = api.request(method, f"/users/{user_b.pk}{suffix}", body)
    unknown = api.request(method, f"/users/{uuid.uuid4()}{suffix}", body)
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    with owner():
        user_b.refresh_from_db()
        assert user_b.is_active
        assert list(UserRole.objects.filter(user=user_b).values_list("role__code", flat=True)) == ["AGENT"]


def test_application_filter_isolates_even_without_rls(admin_a: User, user_b: User) -> None:
    """Défense en profondeur : requête exécutée en rôle propriétaire (RLS contourné) — le filtre applicatif
    sur l'organisme du contexte suffit à lui seul à rendre le compte de B introuvable."""
    api = signed_in(admin_a)
    with owner():
        assert api.get(f"/users/{user_b.pk}").status_code == 404
        assert user_b.email not in api.get("/users").content.decode()


def test_create_uses_server_context_never_the_body(
    admin_a: User, org_a: Organization, org_b: Organization
) -> None:
    response = signed_in(admin_a).post(
        "/users",
        {
            "email": "Nouveau@Demo-A.rbi.test",
            "first_name": "Nina",
            "roles": ["ANALYST"],
            "organization_id": str(org_b.pk),
            "organization": str(org_b.pk),
            "is_superuser": True,
        },
    )
    assert response.status_code == 201, response.content
    assert response.json()["roles"] == ["ANALYST"] and response.json()["email"] == "nouveau@demo-a.rbi.test"
    with owner():
        created = User.objects.get(email="nouveau@demo-a.rbi.test")
        assert created.organization_id == org_a.pk and not created.has_usable_password()
        event = AuditLog.objects.filter(action="user.create", object_id=str(created.pk)).get()
        assert (event.actor_id, event.organization_id) == (admin_a.pk, org_a.pk)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "a@demo-a.rbi.test", "roles": ["SUPER_ADMIN"]}, "roles"),
        ({"email": "a@demo-a.rbi.test", "roles": ["AGENT", "AGENT"]}, "roles"),
        ({"email": "pas-une-adresse"}, "email"),
        ({"first_name": "Sans adresse"}, "email"),
    ],
)
def test_create_validates_input(admin_a: User, body: dict[str, Any], field: str) -> None:
    response = signed_in(admin_a).post("/users", body)
    assert response.status_code == 400
    assert {key.split(".")[0] for key in response.json()["errors"]} == {
        field
    }  # « roles.0 » : élément de liste


def test_create_with_existing_address_is_refused_generically(admin_a: User, user_b: User) -> None:
    response = signed_in(admin_a).post("/users", {"email": user_b.email})
    assert response.status_code == 400
    assert response.json()["errors"] == {"email": ["Cette adresse ne peut pas être utilisée."]}


def test_role_assignment_and_revocation(admin_a: User, user_a: User) -> None:
    api = signed_in(admin_a)
    assert api.post(f"/users/{user_a.pk}/roles", {"role": "SUPERVISOR"}).json()["roles"] == ["SUPERVISOR"]
    assert api.post(f"/users/{user_a.pk}/roles", {"role": "SUPER_ADMIN"}).status_code == 400
    assert api.delete(f"/users/{user_a.pk}/roles/SUPERVISOR").status_code == 204
    assert api.get(f"/users/{user_a.pk}").json()["roles"] == []
    assert api.delete(f"/users/{user_a.pk}/roles/SUPER_ADMIN").status_code == 400


def test_self_management_and_last_admin_are_refused(admin_a: User) -> None:
    api = signed_in(admin_a)
    assert api.patch(f"/users/{admin_a.pk}", {"is_active": False}).status_code == 403
    assert api.post(f"/users/{admin_a.pk}/roles", {"role": "AGENT"}).status_code == 403
    assert api.post(f"/users/{admin_a.pk}/mfa-reset").status_code == 403
    response = api.delete(f"/users/{admin_a.pk}/roles/ORG_ADMIN")
    assert response.status_code == 409 and response.json()["title"] == "Opération impossible"


def test_deactivation_and_mfa_reset(admin_a: User, user_a: User) -> None:
    api = signed_in(admin_a)
    assert api.patch(f"/users/{user_a.pk}", {"is_active": False}).json()["is_active"] is False
    assert api.patch(f"/users/{user_a.pk}", {"is_active": "peut-être"}).status_code == 400
    with owner():
        TOTPDevice.objects.create(user=user_a, name="totp", confirmed=True)
    assert api.post(f"/users/{user_a.pk}/mfa-reset").status_code == 204
    with owner():
        assert not TOTPDevice.objects.filter(user=user_a).exists()


def test_roles_catalog_lists_organization_roles_only(admin_a: User) -> None:
    codes = {role["code"] for role in signed_in(admin_a).get("/roles").json()}
    assert codes == {"ORG_ADMIN", "SUPERVISOR", "AGENT", "ANALYST", "AUDITOR"}
