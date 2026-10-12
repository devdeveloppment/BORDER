"""Preuves ciblées sur deux garanties du cycle de vie.

1. Un service global appelé sans PlatformScope est refusé AVANT toute lecture ou écriture SQL
   (pas seulement annulé ensuite).
2. Les préconditions de statut sont évaluées sur la ligne verrouillée en base, jamais sur l'objet en mémoire.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.organizations import selectors, services
from apps.organizations.exceptions import InvalidTransition, PlatformAccessDenied
from apps.organizations.models import AccessRequest, Organization
from apps.organizations.platform import PlatformScope, platform_scope
from apps.users.models import User
from conftest import OrganizationFactory, add_authorization, owner

pytestmark = pytest.mark.django_db

Status = Organization.Status
D = datetime.date(2026, 1, 1)

GLOBAL_OPERATIONS: dict[str, Callable[[Any, Organization, AccessRequest], object]] = {
    "register_organization": lambda s, o, r: services.register_organization(
        s, name="X", short_name="X", type="autre", country_code="TG", timezone="UTC", retention_days=1
    ),
    "update_organization": lambda s, o, r: services.update_organization(s, o, retention_days=10),
    "authorize_organization": lambda s, o, r: services.authorize_organization(
        s, o, reference="R", scope_text="S", valid_from=D
    ),
    "add_authorization": lambda s, o, r: services.add_authorization(
        s, o, reference="R", scope_text="S", valid_from=D
    ),
    "activate_organization": lambda s, o, r: services.activate_organization(s, o),
    "suspend_organization": lambda s, o, r: services.suspend_organization(s, o, reason="motif"),
    "reactivate_organization": lambda s, o, r: services.reactivate_organization(s, o, reason="motif"),
    "archive_organization": lambda s, o, r: services.archive_organization(s, o, reason="motif"),
    "reject_access_request": lambda s, o, r: services.reject_access_request(s, r, reason="motif"),
    "list_organizations": lambda s, o, r: list(selectors.list_organizations(s)),
    "pending_access_requests": lambda s, o, r: list(selectors.pending_access_requests(s)),
}


TRANSACTION_CONTROL = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")
SCOPE_CONTROL = "SELECT set_config('app."  # pose du périmètre RLS (P2.6) : pas une lecture de données
# Enregistrement du refus dans le journal d'audit (P2.7, mode inline des tests) : attendu, et vérifié à part.
AUDIT_WRITE = ("SELECT current_user", "SET ROLE ", "INSERT INTO audit_auditlog ")


def data_statements(queries: CaptureQueriesContext) -> list[str]:
    """Instructions SQL hors contrôle de transaction (SAVEPOINT ouvert/annulé par @transaction.atomic) et hors
    écriture de l'événement d'audit du refus."""
    return [
        q["sql"]
        for q in queries
        if not q["sql"].startswith(TRANSACTION_CONTROL)
        and not q["sql"].startswith(SCOPE_CONTROL)
        and not q["sql"].startswith(AUDIT_WRITE)
    ]


def audit_writes(queries: CaptureQueriesContext) -> list[str]:
    return [q["sql"] for q in queries if q["sql"].startswith("INSERT INTO audit_auditlog ")]


@pytest.fixture
def pending_request() -> AccessRequest:
    return services.submit_access_request(
        organization_name="Organisme Demandeur Fictif",
        requester_name="Personne Fictive",
        requester_role="Directeur",
        email="contact@demandeur.rbi.test",
        request_type="acces",
        consent=True,
    )


@pytest.mark.parametrize("operation", sorted(GLOBAL_OPERATIONS))
def test_global_operation_refused_before_any_sql(
    operation: str, user_a: User, org_a: Organization, pending_request: AccessRequest
) -> None:
    """Utilisateur organisationnel passé à la place d'un PlatformScope : aucune lecture ni écriture."""
    with CaptureQueriesContext(connection) as queries, pytest.raises(PlatformAccessDenied):
        GLOBAL_OPERATIONS[operation](user_a, org_a, pending_request)
    assert data_statements(queries) == []
    assert len(audit_writes(queries)) == 1  # le refus, et lui seul, est enregistré dans le journal


@pytest.fixture
def scope(platform_admin: User) -> PlatformScope:
    return platform_scope(platform_admin, purpose="tests")


def test_activate_ignores_stale_in_memory_status(
    scope: PlatformScope, platform_admin: User, make_organization: OrganizationFactory
) -> None:
    """En mémoire : AUTORISÉE ; en base : SUSPENDUE. L'activation doit être refusée (sinon elle réactiverait
    l'organisme sans motif en contournant reactivate_organization)."""
    org = make_organization(status=Status.AUTORISEE)
    add_authorization(org, platform_admin)
    with owner():
        Organization.objects.filter(pk=org.pk).update(status=Status.SUSPENDUE)
    assert org.status == Status.AUTORISEE  # objet périmé
    with CaptureQueriesContext(connection) as queries, pytest.raises(InvalidTransition, match="SUSPENDUE"):
        services.activate_organization(scope, org)
    first_read = data_statements(queries)[0]
    assert first_read.startswith("SELECT") and first_read.endswith("FOR UPDATE")  # la ligne verrouillée
    with owner():
        assert Organization.objects.get(pk=org.pk).status == Status.SUSPENDUE


def test_reactivate_ignores_stale_in_memory_status(
    scope: PlatformScope, platform_admin: User, make_organization: OrganizationFactory
) -> None:
    """En mémoire : SUSPENDUE ; en base : AUTORISÉE. La réactivation doit être refusée (sinon elle activerait
    un organisme jamais activé par le chemin de réactivation)."""
    org = make_organization(status=Status.SUSPENDUE)
    add_authorization(org, platform_admin)
    with owner():
        Organization.objects.filter(pk=org.pk).update(status=Status.AUTORISEE)
    assert org.status == Status.SUSPENDUE  # objet périmé
    with CaptureQueriesContext(connection) as queries, pytest.raises(InvalidTransition, match="AUTORISEE"):
        services.reactivate_organization(scope, org, reason="motif")
    first_read = data_statements(queries)[0]
    assert first_read.startswith("SELECT") and first_read.endswith("FOR UPDATE")
    with owner():
        assert Organization.objects.get(pk=org.pk).status == Status.AUTORISEE
