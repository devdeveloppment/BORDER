"""API des organismes (P2.8) : son organisme, registre et cycle de vie plateforme (CA-11), demandes
d'accès."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from apps.audit.models import AuditLog
from apps.core.tests.api_support import ApiClient, signed_in
from apps.organizations.models import AccessRequest, Organization
from apps.users.models import User
from conftest import add_authorization, create_user, owner

pytestmark = pytest.mark.django_db

P1_PLATFORM_ORGANIZATION = {
    "id",
    "name",
    "short_name",
    "type",
    "status",
    "country_code",
    "timezone",
    "deployment_mode",
    "is_demo",
    "users_count",
    "authorization_reference",
    "valid_from",
    "valid_until",
    "created_at",
}
P1_ACCESS_REQUEST = {
    "id",
    "organization_name",
    "requester_name",
    "requester_role",
    "email",
    "request_type",
    "created_at",
}
NEW_ORG = {
    "name": "Organisme Démo API",
    "short_name": "DEMO-API",
    "type": "douane",
    "country_code": "TG",
    "timezone": "Africa/Lome",
    "retention_days": 365,
    "is_demo": True,
}


def test_own_organization(admin_a: User, user_a: User, org_a: Organization, platform_admin: User) -> None:
    add_authorization(org_a, platform_admin, reference="CONV-DEMO-A")
    body = signed_in(admin_a).get("/organization").json()
    assert set(body) == P1_PLATFORM_ORGANIZATION
    assert (body["id"], body["users_count"], body["authorization_reference"]) == (
        str(org_a.pk),
        2,
        "CONV-DEMO-A",
    )


def test_registry_counts_accounts_without_exposing_them(
    platform_admin: User, admin_a: User, user_a: User, admin_b: User, org_a: Organization, org_b: Organization
) -> None:
    with owner():
        AccessRequest.objects.create(
            organization_name="Demandeur Fictif",
            requester_name="Personne Fictive",
            requester_role="Directeur",
            email="demande@demandeur.rbi.test",
            request_type="acces",
            consent=True,
        )
    response = signed_in(platform_admin).get("/platform/organizations")
    assert response.status_code == 200
    body = response.json()
    counts = {o["short_name"]: o["users_count"] for o in body["organizations"]}
    assert counts["DEMO-A"] == 2 and counts["DEMO-B"] == 1
    assert all(set(o) == P1_PLATFORM_ORGANIZATION for o in body["organizations"])
    assert [set(r) for r in body["access_requests"]] == [P1_ACCESS_REQUEST]
    text = response.content.decode()
    assert admin_a.email not in text and str(user_a.pk) not in text  # aucun compte d'organisme exposé


def test_full_lifecycle_over_http_is_audited(platform_admin: User) -> None:
    """CA-11 : le Super Administrateur enregistre, autorise, dote d'un administrateur, active, suspend,
    réactive et archive un organisme ; chaque étape est journalisée."""
    api = signed_in(platform_admin)
    created = api.post("/platform/organizations", NEW_ORG)
    assert created.status_code == 201, created.content
    org_id = created.json()["id"]
    base = f"/platform/organizations/{org_id}"
    assert created.json()["status"] == "EN_ATTENTE"
    authorized = api.post(
        f"{base}/authorizations",
        {"reference": "CONV-API-1", "scope": "Périmètre fictif", "valid_from": "2026-01-01"},
    )
    assert authorized.status_code == 201 and authorized.json()["status"] == "AUTORISEE"
    refused = api.post(f"{base}/status", {"action": "activate"})
    assert refused.status_code == 409 and "Administrateur" in refused.json()["detail"]
    admin = api.post(f"{base}/institutional-admins", {"email": "Admin@Demo-Api.rbi.test"})
    assert admin.status_code == 201 and admin.json()["email"] == "admin@demo-api.rbi.test"
    assert api.post(f"{base}/status", {"action": "activate"}).json()["status"] == "ACTIVE"
    assert api.post(f"{base}/status", {"action": "suspend"}).status_code == 400  # motif obligatoire
    assert (
        api.post(f"{base}/status", {"action": "suspend", "reason": "Contrôle"}).json()["status"]
        == "SUSPENDUE"
    )
    assert api.post(f"{base}/status", {"action": "reactivate", "reason": "Fin"}).json()["status"] == "ACTIVE"
    assert api.patch(base, {"retention_days": 730}).json()["retention_days"] == 730
    assert api.post(f"{base}/status", {"action": "archive", "reason": "Fin"}).json()["status"] == "ARCHIVEE"
    assert api.post(f"{base}/status", {"action": "reactivate", "reason": "x"}).status_code == 409
    with owner():
        transitions = list(
            AuditLog.objects.filter(
                organization_id=org_id, action="organization.transition", outcome="success"
            )
            .order_by("id")
            .values_list("new_value", flat=True)
        )
    statuses = [t["status"] for t in transitions]  # type: ignore[index]
    assert statuses == ["AUTORISEE", "ACTIVE", "SUSPENDUE", "ACTIVE", "ARCHIVEE"]


def test_unknown_organization_is_404(platform_admin: User) -> None:
    api = signed_in(platform_admin)
    for method, suffix, body in (
        ("GET", "", None),
        ("PATCH", "", {"retention_days": 10}),
        ("POST", "/status", {"action": "activate"}),
        ("POST", "/authorizations", {"reference": "R", "scope": "S", "valid_from": "2026-01-01"}),
        ("POST", "/institutional-admins", {"email": "x@demo.rbi.test"}),
    ):
        assert api.request(method, f"/platform/organizations/{uuid.uuid4()}{suffix}", body).status_code == 404


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({**NEW_ORG, "timezone": "Mars/Olympus"}, "timezone"),
        ({**NEW_ORG, "retention_days": 0}, "retention_days"),
        ({**NEW_ORG, "type": "armee"}, "type"),
        ({**NEW_ORG, "short_name": "DEMO-A"}, "short_name"),
    ],
)
def test_registration_validates_input(
    platform_admin: User, org_a: Organization, body: dict[str, Any], field: str
) -> None:
    response = signed_in(platform_admin).post("/platform/organizations", body)
    assert response.status_code == 400
    assert any(
        key.split(".")[0] in (field, "non_field_errors", "__all__") for key in response.json()["errors"]
    )


def test_access_request_reject(platform_admin: User) -> None:
    created = ApiClient().post(
        "/public/access-requests",
        {
            "organization": "Demandeur Fictif",
            "role": "Directeur",
            "name": "Personne Fictive",
            "email": "demande@demandeur.rbi.test",
            "request_type": "acces",
            "consent": "true",
        },
    )
    assert created.status_code == 201
    with owner():
        request_id = AccessRequest.objects.get(email="demande@demandeur.rbi.test").pk
    api = signed_in(platform_admin)
    path = f"/platform/access-requests/{request_id}/reject"
    assert api.post(path, {"reason": ""}).status_code == 400
    assert api.post(path, {"reason": "Hors périmètre"}).status_code == 200
    assert api.post(path, {"reason": "Encore"}).status_code == 409
    assert api.post(f"/platform/access-requests/{uuid.uuid4()}/reject", {"reason": "x"}).status_code == 404


def test_organization_admin_cannot_reach_platform_operations(admin_a: User, org_a: Organization) -> None:
    api = signed_in(admin_a)
    assert api.get("/platform/organizations").status_code == 403
    assert (
        api.post(
            f"/platform/organizations/{org_a.pk}/status", {"action": "suspend", "reason": "x"}
        ).status_code
        == 403
    )
    with owner():
        assert Organization.objects.get(pk=org_a.pk).status == "ACTIVE"


def test_institutional_admin_designation_requires_its_own_permission(org_a: Organization) -> None:
    """Un compte plateforme ayant platform.organizations mais pas platform.institutional_admins est refusé."""
    from apps.users.models import Permission, Role, RolePermission, UserRole

    manager = create_user("gestionnaire@plateforme.rbi.test")
    with owner():
        role = Role.objects.create(code="ORG_MANAGER_TEST", name="Test", scope="platform", mfa_required=True)
        RolePermission.objects.create(
            role=role, permission=Permission.objects.get(code="platform.organizations")
        )
        UserRole.objects.create(user=manager, role=role, scope="platform")
    api = signed_in(manager)
    assert api.get("/platform/organizations").status_code == 200
    response = api.post(
        f"/platform/organizations/{org_a.pk}/institutional-admins", {"email": "x@demo-a.rbi.test"}
    )
    assert response.status_code == 403
