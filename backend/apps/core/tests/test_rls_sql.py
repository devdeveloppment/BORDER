"""SQL direct sous le rôle applicatif : le RLS PostgreSQL isole les organismes SANS aucun filtre de l'ORM.

Le corps de chaque test s'exécute en ``rbi_app`` (conftest racine) ; les données sont préparées en
propriétaire.
Le contexte est posé soit par ``db_scope`` (mécanisme de production), soit par ``set_config`` brut pour
montrer
que les politiques ne dépendent pas du code Python.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.db_scope import db_scope, identity_scope
from apps.integrations.models import DataSource
from apps.organizations.models import AccessRequest, Organization
from apps.organizations.tenancy import TenantContext, tenant_context
from apps.users.models import User
from conftest import add_authorization, create_user, grant_role, owner

pytestmark = pytest.mark.django_db


def rows(query: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(query, params or [])
        return list(cursor.fetchall()) if cursor.description else []


def affected(query: str, params: list[Any] | None = None) -> int:
    with connection.cursor() as cursor:
        cursor.execute(query, params or [])
        return int(cursor.rowcount)


def denied(query: str, params: list[Any] | None = None) -> str:
    """La requête échoue (RLS ou privilège) ; la transaction de test reste utilisable (point de
    sauvegarde)."""
    with pytest.raises(DatabaseError) as excinfo, transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(query, params or [])
    return str(excinfo.value)


def ids(table: str, column: str = "id") -> set[Any]:
    return {row[0] for row in rows(f"SELECT {column} FROM {table}")}  # noqa: S608 - noms constants des tests


@dataclass
class World:
    org_a: Organization
    org_b: Organization
    admin_a: User
    agent_a: User
    agent_b: User
    source_a: uuid.UUID
    source_b: uuid.UUID
    device_a: int
    device_b: int


@pytest.fixture
def world(org_a: Organization, org_b: Organization, platform_admin: User) -> World:
    admin_a = create_user("admin@demo-a.rbi.test", org_a)
    grant_role(admin_a, "ORG_ADMIN")
    agent_a = create_user("agent@demo-a.rbi.test", org_a)
    grant_role(agent_a, "AGENT")
    agent_b = create_user("agent@demo-b.rbi.test", org_b)
    grant_role(agent_b, "AGENT")
    add_authorization(org_a, platform_admin, reference="CONV-A")
    add_authorization(org_b, platform_admin, reference="CONV-B")
    with owner():
        with tenant_context(TenantContext(org_a.pk, "task")):
            source_a = DataSource.objects.create(name="Source A", source_type="manuelle").pk
        with tenant_context(TenantContext(org_b.pk, "task")):
            source_b = DataSource.objects.create(name="Source B", source_type="manuelle").pk
        device_a = TOTPDevice.objects.create(user=agent_a, name="A", confirmed=True).pk
        device_b = TOTPDevice.objects.create(user=agent_b, name="B", confirmed=True).pk
        AccessRequest.objects.create(
            organization_name="Demandeur fictif",
            requester_name="Personne fictive",
            requester_role="Directeur",
            email="demande@demandeur.rbi.test",
            request_type="acces",
            consent=True,
        )
    return World(org_a, org_b, admin_a, agent_a, agent_b, source_a, source_b, device_a, device_b)


@pytest.fixture
def as_org_a(world: World) -> Iterator[None]:
    with db_scope(current_org=world.org_a.pk, current_user=world.agent_a.pk, auth_email="", platform=""):
        yield


def test_runs_as_application_role(world: World) -> None:
    import os

    current, _session = rows("SELECT current_user, session_user")[0]
    assert current == os.environ["RBI_DB_APP_USER"]


# --- A. Données d'un organisme --------------------------------------------------------------------------


def test_no_context_sees_nothing(world: World) -> None:
    for table in (
        "integrations_datasource",
        "organizations_organization",
        "organizations_organizationauthorization",
        "organizations_accessrequest",
        "users_user",
        "users_user_role",
        "otp_totp_totpdevice",
        "authentication_mfa_backup_code",
    ):
        assert rows(f"SELECT count(*) FROM {table}") == [(0,)], table  # noqa: S608


def test_no_context_writes_refused(world: World) -> None:
    assert "row-level security" in denied(
        "INSERT INTO integrations_datasource (id, organization_id, name, source_type, legal_basis_ref, "
        "status, "
        "created_at, updated_at) VALUES (%s, %s, 'X', 'manuelle', '', 'active', now(), now())",
        [uuid.uuid4(), world.org_a.pk],
    )
    assert affected("UPDATE integrations_datasource SET name = 'X'") == 0
    assert affected("DELETE FROM integrations_datasource") == 0


def test_organization_a_reads_only_its_rows(world: World, as_org_a: None) -> None:
    assert ids("integrations_datasource") == {world.source_a}
    assert rows("SELECT name FROM integrations_datasource WHERE id = %s", [world.source_b]) == []
    assert ids("organizations_organization") == {world.org_a.pk}
    assert ids("users_user") == {world.admin_a.pk, world.agent_a.pk}
    assert ids("organizations_organizationauthorization", "organization_id") == {world.org_a.pk}


def test_raw_set_config_is_enough(world: World) -> None:
    """Les politiques ne dépendent que de la variable PostgreSQL : SQL brut, sans Python. L'annulation du
    point de
    sauvegarde retire le contexte (sémantique de SET LOCAL ; db_scope restaure aussi à la sortie normale)."""
    with transaction.atomic():
        rows("SELECT set_config('app.current_org', %s, true)", [str(world.org_b.pk)])
        assert ids("integrations_datasource") == {world.source_b}
        transaction.set_rollback(True)
    assert rows("SELECT count(*) FROM integrations_datasource") == [(0,)]


def test_organization_a_cannot_modify_or_delete_b(world: World, as_org_a: None) -> None:
    assert (
        affected("UPDATE integrations_datasource SET name = 'Pris par A' WHERE id = %s", [world.source_b])
        == 0
    )
    assert affected("DELETE FROM integrations_datasource WHERE id = %s", [world.source_b]) == 0
    assert affected("UPDATE integrations_datasource SET name = name") == 1  # seulement sa propre ligne
    with owner():
        assert rows("SELECT name FROM integrations_datasource WHERE id = %s", [world.source_b]) == [
            ("Source B",)
        ]


def test_organization_a_cannot_create_for_b(world: World, as_org_a: None) -> None:
    message = denied(
        "INSERT INTO integrations_datasource (id, organization_id, name, source_type, legal_basis_ref, "
        "status, "
        "created_at, updated_at) VALUES (%s, %s, 'Injection', 'manuelle', '', 'active', now(), now())",
        [uuid.uuid4(), world.org_b.pk],
    )
    assert "row-level security" in message


def test_transfer_to_another_organization_refused(world: World, as_org_a: None) -> None:
    assert "row-level security" in denied(
        "UPDATE integrations_datasource SET organization_id = %s WHERE id = %s",
        [world.org_b.pk, world.source_a],
    )


@pytest.mark.parametrize("value", ["pas-un-uuid", "' OR 1=1 --", "00000000-0000-0000-0000-00000000000g"])
def test_malformed_context_fails_safely(world: World, value: str) -> None:
    with transaction.atomic():
        rows("SELECT set_config('app.current_org', %s, true)", [value])
        message = denied("SELECT count(*) FROM integrations_datasource")
    assert "uuid" in message.lower()


def test_unknown_organization_context_sees_nothing(world: World) -> None:
    with db_scope(current_org=uuid.uuid4(), current_user="", auth_email="", platform=""):
        assert rows("SELECT count(*) FROM integrations_datasource") == [(0,)]


# --- A. Tentatives de contournement --------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE integrations_datasource DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE integrations_datasource NO FORCE ROW LEVEL SECURITY",
        "DROP POLICY rbi_tenant_isolation ON integrations_datasource",
        "CREATE POLICY rbi_open ON integrations_datasource USING (true)",
        "ALTER TABLE integrations_datasource OWNER TO CURRENT_USER",
        "TRUNCATE integrations_datasource",
        "TRUNCATE users_user CASCADE",
        "CREATE TABLE rbi_intrusion (id int)",
        "ALTER ROLE CURRENT_USER BYPASSRLS",
        "ALTER ROLE CURRENT_USER SUPERUSER",
    ],
)
def test_application_role_cannot_escape_rls(world: World, statement: str) -> None:
    denied(statement)


def test_grant_by_application_role_has_no_effect(world: World) -> None:
    """GRANT sur une table d'autrui : PostgreSQL n'accorde rien (simple avertissement)."""
    rows("GRANT ALL ON integrations_datasource TO PUBLIC")
    with owner():
        assert rows("SELECT has_table_privilege('public', 'integrations_datasource', 'DELETE')") == [(False,)]


# Les changements de rôle (SET ROLE, SET SESSION AUTHORIZATION) sont testés sur une vraie connexion ouverte
# avec le
# rôle applicatif (test_rls_connections) : ici, l'utilisateur de session est le propriétaire du harnais de
# test.


# --- A. Identité, rôles et MFA -------------------------------------------------------------------------


def test_login_lookup_sees_only_the_searched_account(world: World) -> None:
    with db_scope(current_user="", current_org="", auth_email=world.agent_b.email, platform=""):
        assert ids("users_user") == {world.agent_b.pk}
        assert ids("organizations_organization") == {world.org_b.pk}
        assert rows("SELECT count(*) FROM otp_totp_totpdevice") == [(0,)]  # aucun secret
        assert rows("SELECT count(*) FROM integrations_datasource") == [(0,)]


def test_identity_scope_sees_only_own_secrets(world: World) -> None:
    with identity_scope(world.agent_a.pk):
        assert ids("otp_totp_totpdevice") == {world.device_a}
        assert ids("users_user") == {world.agent_a.pk}
        assert rows("SELECT count(*) FROM integrations_datasource") == [(0,)]  # pas de données métier
        assert affected("DELETE FROM otp_totp_totpdevice WHERE id = %s", [world.device_b]) == 0
        assert "row-level security" in denied(
            "INSERT INTO otp_totp_totpdevice (user_id, name, confirmed, key, step, t0, digits, tolerance, "
            "drift, "
            "last_t, throttling_failure_timestamp, throttling_failure_count) "
            "VALUES (%s, 'x', true, '00', 30, 0, 6, 1, 0, -1, NULL, 0)",
            [world.agent_b.pk],
        )


def test_same_organization_context_does_not_expose_colleagues_secrets(world: World, as_org_a: None) -> None:
    with db_scope(current_user=world.admin_a.pk):
        assert rows("SELECT count(*) FROM otp_totp_totpdevice") == [
            (0,)
        ]  # l'admin ne lit pas le TOTP de l'agent


def test_user_cannot_change_own_organization(world: World, as_org_a: None) -> None:
    assert "row-level security" in denied(
        "UPDATE users_user SET organization_id = %s WHERE id = %s", [world.org_b.pk, world.agent_a.pk]
    )
    assert affected("UPDATE users_user SET is_active = false WHERE id = %s", [world.agent_b.pk]) == 0


def test_role_assignments_isolated(world: World, as_org_a: None) -> None:
    assert ids("users_user_role", "organization_id") == {world.org_a.pk}
    role = rows("SELECT id FROM users_role WHERE code = 'ORG_ADMIN' AND scope = 'organization'")[0][0]
    insert = (
        "INSERT INTO users_user_role (user_id, role_id, scope, organization_id, created_at) "
        "VALUES (%s, %s, %s, %s, now())"
    )
    assert "row-level security" in denied(insert, [world.agent_b.pk, role, "organization", world.org_b.pk])
    super_admin = rows("SELECT id FROM users_role WHERE code = 'SUPER_ADMIN'")[0][0]
    assert "row-level security" in denied(insert, [world.agent_a.pk, super_admin, "platform", None])
    assert affected("DELETE FROM users_user_role WHERE organization_id = %s", [world.org_b.pk]) == 0


def test_catalog_is_read_only(world: World, as_org_a: None) -> None:
    assert rows("SELECT count(*) FROM users_permission")[0][0] > 0
    for statement in (
        "UPDATE users_role SET mfa_required = false",
        "DELETE FROM users_role_permission",
        "INSERT INTO users_permission (id, code, module, scope, description) "
        "VALUES (gen_random_uuid(), 'x.y', 'x', 'organization', 'x')",
        "DELETE FROM django_migrations",
    ):
        assert "permission denied" in denied(statement)


def test_organization_status_only_under_platform_scope(world: World, as_org_a: None) -> None:
    assert (
        affected("UPDATE organizations_organization SET status = 'ARCHIVEE' WHERE id = %s", [world.org_a.pk])
        == 0
    )
    assert "permission denied" in denied(
        "DELETE FROM organizations_organization WHERE id = %s", [world.org_a.pk]
    )
    with db_scope(current_org="", platform="platform.organizations"):
        assert ids("organizations_organization") >= {world.org_a.pk, world.org_b.pk}
        assert ids("users_user") == {world.agent_a.pk}  # la plateforme ne lit pas les comptes des organismes


def test_access_requests(world: World) -> None:
    pending = (
        "INSERT INTO organizations_accessrequest (id, organization_name, requester_name, requester_role, "
        "email, "
        "phone, request_type, message, consent, status, created_at, updated_at, processed_at) "
        "VALUES (gen_random_uuid(), 'O', 'N', 'F', 'e@x.test', '', 'acces', '', true, %s, now(), now(), %s)"
    )
    assert affected(pending, ["EN_ATTENTE", None]) == 1  # formulaire public
    assert "row-level security" in denied(pending, ["TRAITEE", "2026-10-08"])  # pas de demande « traitée »
    assert rows("SELECT count(*) FROM organizations_accessrequest") == [(0,)]  # illisibles hors plateforme
    with db_scope(platform="platform.organizations"):
        assert rows("SELECT count(*) FROM organizations_accessrequest") == [(2,)]


# --- A. Fonctions SECURITY DEFINER ---------------------------------------------------------------------


def test_org_has_active_admin_requires_platform_scope(world: World) -> None:
    assert "plateforme" in denied("SELECT rbi_org_has_active_admin(%s)", [world.org_a.pk])
    with db_scope(platform="platform.organizations"):
        assert rows("SELECT rbi_org_has_active_admin(%s)", [world.org_a.pk]) == [(True,)]
        assert rows("SELECT rbi_org_has_active_admin(%s)", [world.org_b.pk]) == [(False,)]


def test_admin_reset_mfa_function_is_bounded(world: World) -> None:
    call = "SELECT rbi_admin_reset_mfa(%s)"
    denied(call, [world.agent_a.pk])  # aucun périmètre
    with db_scope(current_org=world.org_a.pk, current_user=world.agent_a.pk):
        denied(call, [world.admin_a.pk])  # un agent n'a pas users.manage
    with db_scope(current_org=world.org_a.pk, current_user=world.admin_a.pk):
        assert "introuvable" in denied(call, [world.agent_b.pk])  # compte d'un autre organisme
        denied(call, [world.admin_a.pk])  # pas sur soi-même
        rows(call, [world.agent_a.pk])
    with owner():
        assert not TOTPDevice.objects.filter(pk=world.device_a).exists()
        assert TOTPDevice.objects.filter(pk=world.device_b).exists()


def test_current_user_org_reveals_only_own_organization(world: World) -> None:
    assert rows("SELECT rbi_current_user_org()") == [(None,)]
    with identity_scope(world.agent_b.pk):
        assert rows("SELECT rbi_current_user_org()") == [(world.org_b.pk,)]
