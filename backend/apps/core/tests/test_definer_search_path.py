"""Fonctions ``SECURITY DEFINER`` : ``search_path`` sûr, ``pg_temp`` en dernier (migration ``core.0003``).

Défaut découvert en P2.11 : avec ``search_path = pg_catalog, public``, une table temporaire créée par le rôle
applicatif masquait la table de ``public`` du même nom dans ces fonctions, exécutées avec les droits du
propriétaire. Les essais ci-dessous créent ces tables temporaires sous le rôle applicatif, dans la base de
test et dans la transaction du test (annulée ensuite) ; chacun vérifie d'abord que la session voit bien la
table temporaire, puis que la fonction l'ignore.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.integrity import PLATFORM_CHAIN, verify_chain
from apps.audit.services import record_event
from apps.core.db_scope import db_scope
from apps.organizations.models import Organization
from apps.users.models import User
from conftest import owner

pytestmark = pytest.mark.django_db

SAFE_CONFIG = ["search_path=pg_catalog, public, pg_temp"]
DEFINER_FUNCTIONS = {
    "rbi_admin_reset_mfa",
    "rbi_audit_org_reader",
    "rbi_audit_platform_reader",
    "rbi_audit_seal",
    "rbi_current_user_org",
    "rbi_org_has_active_admin",
    "rbi_org_mfa_enabled_users",
    "rbi_platform_org_user_counts",
}
SHADOWS = {
    # security_stamp : rbi_admin_reset_mfa le met à jour ; sans cette colonne, l'essai échouerait pour une
    # autre raison que la protection testée (constaté par la contre-épreuve SP-03).
    "users_user": "id uuid, organization_id uuid, is_active boolean, security_stamp uuid",
    "users_user_role": "user_id uuid, role_id int, scope text, organization_id uuid",
    "users_role": "id int, scope text, code text",
    "users_role_permission": "role_id int, permission_id int",
    "users_permission": "id int, scope text, code text",
}


def _one(cursor: Any, sql: str, params: list[Any] | None = None) -> Any:
    cursor.execute(sql, params or [])
    row = cursor.fetchone()
    return row[0] if row else None


def _shadow_identity(
    cursor: Any, user: uuid.UUID, *, scope: str, permission: str, organization: uuid.UUID | None
) -> None:
    """Tables temporaires homonymes accordant ``permission`` à ``user`` (compte qui n'existe pas en base)."""
    for table, columns in SHADOWS.items():
        cursor.execute(f"CREATE TEMP TABLE {table} ({columns})")
        # Ouverte au propriétaire des fonctions (lecture et écriture), comme par une session malveillante.
        cursor.execute(f"GRANT ALL ON pg_temp.{table} TO PUBLIC")
    cursor.execute(
        "INSERT INTO pg_temp.users_user (id, organization_id, is_active) VALUES (%s, %s, true)",
        [user, organization],
    )
    cursor.execute("INSERT INTO pg_temp.users_user_role VALUES (%s, 1, %s, %s)", [user, scope, organization])
    cursor.execute("INSERT INTO pg_temp.users_role VALUES (1, %s, 'ROLE')", [scope])
    cursor.execute("INSERT INTO pg_temp.users_role_permission VALUES (1, 1)")
    cursor.execute("INSERT INTO pg_temp.users_permission VALUES (1, %s, %s)", [scope, permission])
    # La session elle-même résout bien le nom vers la table temporaire : l'essai n'est pas vide de sens.
    assert _one(cursor, "SELECT count(*) FROM users_user WHERE id = %s", [user]) == 1


def test_every_security_definer_function_puts_pg_temp_last() -> None:
    with owner(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.proname, p.proconfig FROM pg_proc p "
            "WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef"
        )
        configs = dict(cursor.fetchall())
    # Toutes les fonctions SECURITY DEFINER, pas seulement celles qu'exécute le rôle applicatif.
    assert set(configs) == DEFINER_FUNCTIONS
    assert {name: config for name, config in configs.items() if config != SAFE_CONFIG} == {}


def test_temporary_tables_do_not_fool_the_platform_audit_reader() -> None:
    intruder = uuid.uuid4()
    with transaction.atomic(), connection.cursor() as cursor:
        _shadow_identity(cursor, intruder, scope="platform", permission="platform.audit", organization=None)
        with db_scope(current_user=intruder, current_org="", auth_email="", platform="platform.audit"):
            assert _one(cursor, "SELECT rbi_audit_platform_reader()") is False
            assert _one(cursor, "SELECT count(*) FROM audit_auditlog") == 0  # politique RLS de lecture
        transaction.set_rollback(True)


def test_temporary_tables_do_not_fool_the_organisation_audit_reader(org_a: Organization) -> None:
    intruder = uuid.uuid4()
    with transaction.atomic(), connection.cursor() as cursor:
        _shadow_identity(
            cursor, intruder, scope="organization", permission="audit.view", organization=org_a.pk
        )
        with db_scope(current_user=intruder, current_org=org_a.pk, auth_email="", platform=""):
            assert _one(cursor, "SELECT rbi_audit_org_reader()") is False
        transaction.set_rollback(True)


def test_temporary_tables_do_not_change_the_organisation_of_the_current_account(org_a: Organization) -> None:
    intruder = uuid.uuid4()
    with transaction.atomic(), connection.cursor() as cursor:
        _shadow_identity(
            cursor, intruder, scope="organization", permission="users.view", organization=org_a.pk
        )
        with db_scope(current_user=intruder, current_org="", auth_email="", platform=""):
            assert _one(cursor, "SELECT rbi_current_user_org()") is None
        transaction.set_rollback(True)


def test_temporary_tables_do_not_allow_resetting_another_accounts_mfa(
    user_a: User, org_a: Organization
) -> None:
    with owner():
        TOTPDevice.objects.create(user=user_a, name="RBI", confirmed=True)
    intruder = uuid.uuid4()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        _shadow_identity(
            cursor, intruder, scope="organization", permission="users.manage", organization=org_a.pk
        )
        cursor.execute(
            "INSERT INTO pg_temp.users_user (id, organization_id, is_active) VALUES (%s, %s, true)",
            [user_a.pk, org_a.pk],
        )
        with db_scope(current_user=intruder, current_org=org_a.pk, auth_email="", platform=""):
            cursor.execute("SELECT rbi_admin_reset_mfa(%s)", [user_a.pk])  # refus attendu (42501)
    with owner():
        assert TOTPDevice.objects.filter(user=user_a, confirmed=True).count() == 1


def test_a_temporary_chain_head_does_not_divert_the_audit_seal() -> None:
    with owner():
        assert verify_chain(PLATFORM_CHAIN).intact
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE audit_chain (chain_key varchar(64) PRIMARY KEY, last_id bigint, "
            "last_hash char(64) NOT NULL, length bigint NOT NULL DEFAULT 0, updated_at timestamptz)"
        )
        cursor.execute("GRANT ALL ON pg_temp.audit_chain TO PUBLIC")
        cursor.execute("INSERT INTO pg_temp.audit_chain VALUES ('platform', NULL, repeat('f', 64), 0, NULL)")
        record_event(
            "auth.login", outcome="failure", actor_id=None, details={"reason": "invalid_credentials"}
        )
        assert _one(cursor, "SELECT length FROM pg_temp.audit_chain WHERE chain_key = 'platform'") == 0
        cursor.execute("DROP TABLE pg_temp.audit_chain")  # la vérification lit elle aussi « audit_chain »
        with owner():
            report = verify_chain(PLATFORM_CHAIN)
        assert report.intact, report.errors
        transaction.set_rollback(True)
