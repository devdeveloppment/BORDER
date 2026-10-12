"""Connexion Django → PostgreSQL réelle : pilote psycopg 3, version, PostGIS, migrations, rôles."""

from __future__ import annotations

import io
import os
from typing import Any, cast

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# Vérifications de schéma et de migrations : avec le rôle propriétaire.
pytestmark = [pytest.mark.django_db, pytest.mark.db_owner]

# Attributs propres aux moteurs PostgreSQL / PostGIS, absents du type générique BaseDatabaseWrapper.
pg = cast(Any, connection)


def test_driver_is_psycopg3() -> None:
    from django.db.backends.postgresql.psycopg_any import is_psycopg3

    assert is_psycopg3
    assert connection.vendor == "postgresql"
    assert pg.Database.__name__ == "psycopg"


def test_postgresql_16() -> None:
    assert 160000 <= pg.pg_version < 170000
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user")
        row = cursor.fetchone()
    assert row == ("test_rbi", os.environ["RBI_DB_USER"])  # jamais la base de développement


def test_postgis_extension_present() -> None:
    assert pg.ops.spatial_version >= (3, 0)
    with connection.cursor() as cursor:
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        row = cursor.fetchone()
    assert row is not None and row[0].startswith("3.")


def test_all_migrations_applied() -> None:
    executor = MigrationExecutor(connection)
    assert executor.migration_plan(executor.loader.graph.leaf_nodes()) == []
    applied = {app for app, _ in executor.loader.applied_migrations}
    assert {"contenttypes", "auth", "users", "gisprobe", "organizations", "integrations", "audit"} <= applied


def test_no_missing_migrations() -> None:
    out = io.StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out)
    assert "No changes detected" in out.getvalue()


def test_tables_owned_by_owner() -> None:
    """Toutes les tables appartiennent au rôle propriétaire. Les privilèges exacts du rôle applicatif et le
    RLS
    sont vérifiés table par table contre l'inventaire de sécurité (apps/core/tests/test_rls_inventory.py)."""
    owner = os.environ["RBI_DB_OWNER"]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename, tableowner FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'spatial_ref_sys'"
        )
        tables = dict(cursor.fetchall())
    assert {"users_user", "organizations_organization", "integrations_datasource"} <= tables.keys()
    assert set(tables.values()) == {owner}


@pytest.mark.django_db(transaction=True)
def test_p23_to_p27_migrations_are_reversible() -> None:
    """Retour arrière complet des migrations P2.3 à P2.7, puis réapplication (catalogue resynchronisé)."""

    def tables() -> set[str]:
        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            return {row[0] for row in cursor.fetchall()}

    def user_columns() -> set[str]:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'users_user'"
            )
            return {row[0] for row in cursor.fetchall()}

    p23_tables = {
        "organizations_organization",
        "organizations_organizationauthorization",
        "organizations_accessrequest",
        "integrations_datasource",
        "users_permission",
        "users_role",
        "users_role_permission",
        "users_user_role",
    }
    with connection.cursor() as cursor:
        # P2.7 : retour arrière du journal d'audit refusé s'il contient des entrées, sauf décision explicite
        # du propriétaire dans sa session (vérifié par apps/audit/tests/test_audit_migration.py).
        cursor.execute("SET rbi.audit_allow_drop = 'on'")
    try:
        call_command("migrate", "users", "0001", verbosity=0)  # annule aussi core.0001 (RLS) et audit.0001
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET rbi.audit_allow_drop")
    assert "audit_auditlog" not in tables()
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_policies WHERE schemaname = 'public'")
        assert cursor.fetchone() == (0,)
    call_command("migrate", "integrations", "zero", verbosity=0)
    call_command("migrate", "organizations", "zero", verbosity=0)
    assert not p23_tables & tables()
    assert "organization_id" not in user_columns()
    call_command("migrate", verbosity=0)
    assert p23_tables <= tables()
    assert "organization_id" in user_columns()
    assert "is_superuser" not in user_columns()
    from apps.users.catalog import PERMISSIONS, ROLES
    from apps.users.models import Permission, Role

    assert Permission.objects.count() == len(PERMISSIONS)
    assert Role.objects.filter(is_system=True).count() == len(ROLES)
    with connection.cursor() as cursor:  # P2.6 : RLS et fonctions réinstallés
        cursor.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'integrations_datasource'")
        assert cursor.fetchone() == (True,)
        cursor.execute("SELECT count(*) FROM pg_proc WHERE proname LIKE 'rbi_%%' AND prosecdef")
        assert cursor.fetchone() == (8,)  # P2.6 : 3 ; P2.7 : 2 lecteurs d'audit + scellement ; P2.8 : 2
        cursor.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'audit_auditlog'")
        assert cursor.fetchone() == (True,)
