"""Mécanisme ``db_scope`` (Django) et parcours HTTP / tâches sous le rôle applicatif."""

from __future__ import annotations

import uuid

import pytest
from django.db import DatabaseError, connection, transaction

from apps.authentication.tests.support import PASSWORD, Api, make_member
from apps.core.db_scope import current_scope, database_scope, db_scope, identity_scope
from apps.integrations.models import DataSource
from apps.organizations.exceptions import TenantAccessDenied, TenantContextMissing
from apps.organizations.models import Organization
from apps.organizations.tasking import tenant_task
from apps.organizations.tenancy import TenantContext, tenant_context
from conftest import owner

pytestmark = pytest.mark.django_db

EMPTY = {"current_org": "", "current_user": "", "auth_email": "", "platform": ""}


def test_no_scope_by_default() -> None:
    assert current_scope() == EMPTY
    assert database_scope() == EMPTY


def test_nested_scopes_inherit_and_restore() -> None:
    org, user = uuid.uuid4(), uuid.uuid4()
    with db_scope(current_org=org):
        with db_scope(current_user=user):
            assert database_scope() == {**EMPTY, "current_org": str(org), "current_user": str(user)}
        assert database_scope() == {**EMPTY, "current_org": str(org)}
        with identity_scope(user):
            assert database_scope() == {**EMPTY, "current_user": str(user)}  # efface l'organisme
        assert database_scope() == {**EMPTY, "current_org": str(org)}
    assert database_scope() == EMPTY
    assert current_scope() == EMPTY


def test_scope_restored_after_exception() -> None:
    with pytest.raises(RuntimeError), db_scope(current_org=uuid.uuid4()):
        raise RuntimeError
    assert database_scope() == EMPTY and current_scope() == EMPTY


def test_scope_restored_after_database_error(org_a: Organization) -> None:
    with pytest.raises(DatabaseError), db_scope(current_org=org_a.pk), connection.cursor() as cursor:
        cursor.execute("SELECT 1/0")
    assert database_scope() == EMPTY


@pytest.mark.parametrize("value", ["pas-un-uuid", "1; DROP TABLE users_user", "  "])
def test_invalid_identifiers_rejected_before_sql(value: str) -> None:
    if value.strip():
        with pytest.raises(ValueError), db_scope(current_org=value):
            pass
    assert database_scope() == EMPTY


def test_unknown_keys_rejected() -> None:
    with pytest.raises(ValueError), db_scope(organization_id=uuid.uuid4()):
        pass


def test_values_are_parameters_not_sql() -> None:
    hostile = "x'); DROP TABLE users_user; --"
    with db_scope(auth_email=hostile):
        assert database_scope()["auth_email"] == hostile.lower()  # normalisé, transmis tel quel en paramètre
    with owner(), connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.users_user')")
        assert cursor.fetchone() == ("users_user",)


# --- Requêtes HTTP ------------------------------------------------------------------------------------


def test_no_context_survives_requests(org_a: Organization, org_b: Organization) -> None:
    agent_a = make_member(org_a, "AGENT", "agent.scope@demo-a.rbi.test")
    agent_b = make_member(org_b, "AGENT", "agent.scope@demo-b.rbi.test")
    for agent in (agent_a, agent_b):
        api = Api()
        api.post("/auth/login", {"email": agent.email, "password": PASSWORD})
        assert api.get("/me").json()["organization"]["id"] == str(agent.organization_id)
        assert database_scope() == EMPTY  # même connexion de base : rien ne subsiste après la requête


# --- Tâches asynchrones -------------------------------------------------------------------------------


@tenant_task
def _count_sources(*, organization_id: str) -> int:
    with connection.cursor() as cursor:  # SQL brut : seul le RLS filtre
        cursor.execute("SELECT count(*) FROM integrations_datasource")
        row = cursor.fetchone()
    return int(row[0]) if row else -1


@tenant_task
def _write_then_fail(*, organization_id: str) -> None:
    DataSource.objects.create(name="Écriture annulée", source_type="manuelle")
    raise RuntimeError("échec en cours de tâche")


@pytest.fixture
def two_orgs_with_sources(org_a: Organization, org_b: Organization) -> tuple[Organization, Organization]:
    with owner():
        for org, count in ((org_a, 2), (org_b, 1)):
            with tenant_context(TenantContext(org.pk, "task")):
                for i in range(count):
                    DataSource.objects.create(name=f"Source {i}", source_type="manuelle")
    return org_a, org_b


def test_tasks_see_only_their_organization(two_orgs_with_sources: tuple[Organization, Organization]) -> None:
    org_a, org_b = two_orgs_with_sources
    assert _count_sources(organization_id=str(org_a.pk)) == 2
    assert _count_sources(organization_id=str(org_b.pk)) == 1  # tâche enchaînée : aucun résidu de A
    assert database_scope() == EMPTY


def test_task_without_context_fails_safely(two_orgs_with_sources: tuple[Organization, Organization]) -> None:
    with pytest.raises(TenantContextMissing):
        _count_sources()  # type: ignore[call-arg]
    with pytest.raises(TenantAccessDenied):
        _count_sources(organization_id=str(uuid.uuid4()))
    with connection.cursor() as cursor:  # même sans passer par la tâche : rien de visible
        cursor.execute("SELECT count(*) FROM integrations_datasource")
        assert cursor.fetchone() == (0,)


def test_failing_task_does_not_contaminate_the_next(
    two_orgs_with_sources: tuple[Organization, Organization],
) -> None:
    org_a, org_b = two_orgs_with_sources
    with pytest.raises(RuntimeError), transaction.atomic():
        _write_then_fail(organization_id=str(org_a.pk))
    assert database_scope() == EMPTY
    assert _count_sources(organization_id=str(org_a.pk)) == 2  # écriture annulée
    assert _count_sources(organization_id=str(org_b.pk)) == 1
