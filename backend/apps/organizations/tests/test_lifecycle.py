"""Cycle de vie institutionnel (§9.16) et périmètre plateforme (opérations globales)."""

from __future__ import annotations

import datetime
import json
import logging
from collections.abc import Callable

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.organizations import selectors, services
from apps.organizations.exceptions import InvalidTransition, PlatformAccessDenied
from apps.organizations.models import AccessRequest, Organization
from apps.organizations.platform import PlatformScope, platform_scope
from apps.users.models import User
from apps.users.services import create_institutional_admin
from conftest import OrganizationFactory, add_authorization, owner

pytestmark = pytest.mark.django_db

Status = Organization.Status


@pytest.fixture
def scope(platform_admin: User) -> PlatformScope:
    return platform_scope(platform_admin, purpose="tests")


def audit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "rbi.audit"]


def register(scope: PlatformScope, **overrides: object) -> Organization:
    values: dict[str, object] = {
        "name": "Organisme Démo Cycle",
        "short_name": "DEMO-CYCLE",
        "type": "recettes",
        "country_code": "TG",
        "timezone": "Africa/Lome",
        "retention_days": 730,
        "is_demo": True,
    }
    values.update(overrides)
    return services.register_organization(scope, **values)  # type: ignore[arg-type]


# --- Périmètre plateforme ------------------------------------------------------------------


def test_platform_scope_granted_and_audited(platform_admin: User, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="rbi.audit")
    scope = platform_scope(platform_admin, purpose="revue des demandes")
    assert scope.actor_id == platform_admin.pk
    [event] = audit_events(caplog)
    assert event["action"] == "platform.scope" and event["outcome"] == "success"


@pytest.mark.parametrize(
    ("actor_fixture", "reason"),
    [
        ("user_a", "organization_account"),
        ("platform_user_without_permission", "missing_permission"),
    ],
)
def test_platform_scope_denied_and_audited(
    request: pytest.FixtureRequest, caplog: pytest.LogCaptureFixture, actor_fixture: str, reason: str
) -> None:
    actor = request.getfixturevalue(actor_fixture)
    caplog.set_level(logging.INFO, logger="rbi.audit")
    with pytest.raises(PlatformAccessDenied):
        platform_scope(actor, purpose="tentative")
    [event] = audit_events(caplog)
    assert event["outcome"] == "denied" and event["details"]["reason"] == reason  # type: ignore[index]


def test_organization_user_with_platform_role_row_still_denied(admin_a: User) -> None:
    """Même avec une affectation plateforme insérée en contournant les services, un compte organisationnel
    n'agit jamais au niveau plateforme."""
    from apps.users.models import Role, UserRole

    with owner():
        super_admin = Role.objects.get(code="SUPER_ADMIN", scope="platform")
    with owner():
        UserRole.objects.create(user=admin_a, role=super_admin, scope="platform", organization=None)
    with pytest.raises(PlatformAccessDenied):
        platform_scope(admin_a, purpose="tentative")


def test_platform_scope_denied_for_anonymous_and_inactive(platform_admin: User) -> None:
    from django.contrib.auth.models import AnonymousUser

    with pytest.raises(PlatformAccessDenied):
        platform_scope(AnonymousUser(), purpose="tentative")
    with pytest.raises(PlatformAccessDenied):
        platform_scope(None, purpose="tentative")
    platform_admin.is_active = False
    with pytest.raises(PlatformAccessDenied):
        platform_scope(platform_admin, purpose="tentative")


def test_global_operations_require_a_scope_object(org_a: Organization, user_a: User) -> None:
    """Les services globaux n'acceptent qu'un PlatformScope délivré par la porte d'entrée."""
    with pytest.raises(PlatformAccessDenied):
        services.suspend_organization(user_a, org_a, reason="tentative")  # type: ignore[arg-type]
    with pytest.raises(PlatformAccessDenied):
        selectors.list_organizations(user_a)  # type: ignore[arg-type]
    with owner():
        org_a.refresh_from_db()
    assert org_a.status == Status.ACTIVE


# --- Cycle de vie ----------------------------------------------------------------------------


def test_full_lifecycle(scope: PlatformScope, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="rbi.audit")
    org = register(scope)
    assert org.status == Status.EN_ATTENTE

    authorization = services.authorize_organization(
        scope,
        org,
        reference="CONV-CYCLE-1",
        scope_text="Périmètre fictif",
        valid_from=datetime.date(2026, 1, 1),
    )
    assert org.status == Status.AUTORISEE
    assert authorization.granted_by_id == scope.actor_id

    with pytest.raises(InvalidTransition, match="Administrateur"):
        services.activate_organization(scope, org)  # aucun Administrateur institutionnel désigné
    with owner():
        actor = User.objects.get(pk=scope.actor_id)
    admin_scope = platform_scope(actor, purpose="tests", permission="platform.institutional_admins")
    create_institutional_admin(admin_scope, org, email="admin@demo-cycle.rbi.test")
    services.activate_organization(scope, org)
    assert org.status == Status.ACTIVE
    services.suspend_organization(scope, org, reason="Fin de convention en cours de renouvellement")
    assert org.status == Status.SUSPENDUE
    services.reactivate_organization(scope, org, reason="Convention renouvelée")
    assert org.status == Status.ACTIVE
    services.archive_organization(scope, org, reason="Fin d'autorisation")
    assert org.status == Status.ARCHIVEE

    # P2.7 : lu dans le journal d'audit PostgreSQL (ancienne / nouvelle valeur), pas seulement dans les logs.
    with owner():
        transitions = list(
            AuditLog.objects.filter(
                organization_id=org.pk, action="organization.transition", outcome="success"
            ).values_list("old_value", "new_value", "scope", "actor_id")
        )
    assert {(scope_, actor) for _, _, scope_, actor in transitions} == {("platform", scope.actor_id)}
    assert [(old["status"], new["status"]) for old, new, _, _ in transitions] == [  # type: ignore[index]
        ("EN_ATTENTE", "AUTORISEE"),
        ("AUTORISEE", "ACTIVE"),
        ("ACTIVE", "SUSPENDUE"),
        ("SUSPENDUE", "ACTIVE"),
        ("ACTIVE", "ARCHIVEE"),
    ]


@pytest.mark.parametrize(
    ("start", "operation"),
    [
        (Status.EN_ATTENTE, "activate"),
        (Status.EN_ATTENTE, "suspend"),
        (Status.AUTORISEE, "suspend"),
        (Status.AUTORISEE, "reactivate"),
        (Status.ACTIVE, "activate"),
        (Status.ACTIVE, "reactivate"),
        (Status.SUSPENDUE, "suspend"),
        (Status.ARCHIVEE, "activate"),
        (Status.ARCHIVEE, "reactivate"),
        (Status.ARCHIVEE, "suspend"),
        (Status.ARCHIVEE, "archive"),
    ],
)
def test_invalid_transitions_rejected(
    scope: PlatformScope,
    platform_admin: User,
    make_organization: OrganizationFactory,
    start: str,
    operation: str,
) -> None:
    org = make_organization(status=start)
    add_authorization(org, platform_admin)
    calls: dict[str, Callable[[], object]] = {
        "activate": lambda: services.activate_organization(scope, org),
        "suspend": lambda: services.suspend_organization(scope, org, reason="motif"),
        "reactivate": lambda: services.reactivate_organization(scope, org, reason="motif"),
        "archive": lambda: services.archive_organization(scope, org, reason="motif"),
    }
    call = calls[operation]
    with pytest.raises(InvalidTransition):
        call()
    with owner():
        org.refresh_from_db()
    assert org.status == start


def test_activation_requires_authorization_in_force(
    scope: PlatformScope, platform_admin: User, make_organization: OrganizationFactory
) -> None:
    org = make_organization(status=Status.AUTORISEE)
    with pytest.raises(InvalidTransition, match="autorisation"):
        services.activate_organization(scope, org)
    add_authorization(
        org, platform_admin, valid_from=datetime.date(2025, 1, 1), valid_until=datetime.date(2025, 12, 31)
    )  # expirée
    with pytest.raises(InvalidTransition):
        services.activate_organization(scope, org)
    add_authorization(org, platform_admin, reference="CONV-FUTURE", valid_from=datetime.date(2099, 1, 1))
    with pytest.raises(InvalidTransition):
        services.activate_organization(scope, org)
    with owner():
        org.refresh_from_db()
    assert org.status == Status.AUTORISEE


def test_reason_mandatory(scope: PlatformScope, org_a: Organization) -> None:
    with pytest.raises(ValueError, match="motif"):
        services.suspend_organization(scope, org_a, reason="   ")
    with owner():
        org_a.refresh_from_db()
    assert org_a.status == Status.ACTIVE


def test_update_organization(scope: PlatformScope, org_a: Organization) -> None:
    services.update_organization(scope, org_a, retention_days=1095, timezone="UTC")
    with owner():
        org_a.refresh_from_db()
    assert (org_a.retention_days, org_a.timezone) == (1095, "UTC")
    with pytest.raises(ValueError, match="status"):
        services.update_organization(scope, org_a, status=Status.ARCHIVEE)
    with pytest.raises(ValidationError):
        services.update_organization(scope, org_a, retention_days=0)


def test_archived_organization_is_immutable(
    scope: PlatformScope, make_organization: OrganizationFactory
) -> None:
    org = make_organization(status=Status.ARCHIVEE)
    with pytest.raises(InvalidTransition):
        services.update_organization(scope, org, retention_days=10)
    with pytest.raises(InvalidTransition):
        services.add_authorization(
            scope, org, reference="X", scope_text="Y", valid_from=datetime.date(2026, 1, 1)
        )


# --- Demandes d'accès ------------------------------------------------------------------------

REQUEST = {
    "organization_name": "Organisme Demandeur Fictif",
    "requester_name": "Personne Fictive",
    "requester_role": "Directeur",
    "email": "contact@demandeur.rbi.test",
    "request_type": "acces",
    "message": "Demande fictive.",
}


def test_access_request_creates_no_account_nor_organization() -> None:
    with owner():
        users, orgs = User.objects.count(), Organization.objects.count()
    request = services.submit_access_request(**REQUEST, consent=True)
    assert request.status == AccessRequest.Status.EN_ATTENTE
    with owner():
        assert (User.objects.count(), Organization.objects.count()) == (users, orgs)
    with pytest.raises(ValueError, match="consentement"):
        services.submit_access_request(**REQUEST, consent=False)


def test_access_request_processed_into_organization(scope: PlatformScope) -> None:
    request = services.submit_access_request(**REQUEST, consent=True)
    assert list(selectors.pending_access_requests(scope)) == [request]
    org = register(scope, access_request=request)
    with owner():
        request.refresh_from_db()
    assert request.status == AccessRequest.Status.TRAITEE
    assert request.organization_id == org.pk and request.processed_by_id == scope.actor_id
    assert list(selectors.pending_access_requests(scope)) == []
    with pytest.raises(InvalidTransition):
        services.reject_access_request(scope, request, reason="déjà traitée")


def test_access_request_rejected(scope: PlatformScope) -> None:
    request = services.submit_access_request(**REQUEST, consent=True)
    services.reject_access_request(scope, request, reason="Demande hors périmètre")
    with owner():
        request.refresh_from_db()
    assert request.status == AccessRequest.Status.REJETEE and request.processed_at is not None


def test_reason_longer_than_the_audit_limit_is_refused_before_any_change(
    scope: PlatformScope, make_organization: OrganizationFactory
) -> None:
    org = make_organization()
    with pytest.raises(ValueError, match="500 caractères"):
        services.suspend_organization(scope, org, reason="x" * 501)
    with owner():
        org.refresh_from_db()
    assert org.status == Status.ACTIVE
    services.suspend_organization(scope, org, reason="é" * 500)  # limite incluse : enregistrée intégralement
    with owner():
        event = AuditLog.objects.filter(organization_id=org.pk, action="organization.transition").latest("id")
    assert event.metadata["reason"] == "é" * 500
