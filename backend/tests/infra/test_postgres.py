"""PostgreSQL 16 + PostGIS : versions, séparation des rôles et prérequis réels du RLS."""

from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
import pytest
from psycopg import sql

from .support import connect, env


def role_attributes(conn: psycopg.Connection[Any], role: str) -> dict[str, bool]:
    row = conn.execute(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication, rolinherit "
        "FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()
    assert row is not None, f"rôle {role} introuvable"
    keys = ("super", "bypassrls", "createrole", "createdb", "replication", "inherit")
    return dict(zip(keys, row, strict=True))


def test_postgresql_16_and_postgis(app_conn: psycopg.Connection[Any]) -> None:
    server_version = app_conn.execute("SHOW server_version_num").fetchone()
    assert server_version is not None and 160000 <= int(server_version[0]) < 170000
    postgis = app_conn.execute("SELECT postgis_lib_version()").fetchone()
    assert postgis is not None and postgis[0].startswith("3.")
    point = app_conn.execute("SELECT ST_AsText(ST_SetSRID(ST_MakePoint(1.5, 2.5), 4326))").fetchone()
    assert point == ("POINT(1.5 2.5)",)


def test_database_settings(app_conn: psycopg.Connection[Any]) -> None:
    assert app_conn.execute("SHOW server_encoding").fetchone() == ("UTF8",)
    assert app_conn.execute("SHOW TimeZone").fetchone() in {("UTC",), ("Etc/UTC",)}
    assert app_conn.execute("SHOW password_encryption").fetchone() == ("scram-sha-256",)


def test_app_role_is_unprivileged(app_conn: psycopg.Connection[Any]) -> None:
    attrs = role_attributes(app_conn, env("RBI_DB_APP_USER"))
    assert attrs == {
        "super": False,
        "bypassrls": False,
        "createrole": False,
        "createdb": False,
        "replication": False,
        "inherit": False,
    }
    memberships = app_conn.execute(
        "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = %s",
        (env("RBI_DB_APP_USER"),),
    ).fetchone()
    assert memberships == (0,)


def test_owner_role_is_not_superuser(owner_conn: psycopg.Connection[Any]) -> None:
    attrs = role_attributes(owner_conn, env("RBI_DB_OWNER"))
    assert attrs["super"] is False
    assert attrs["bypassrls"] is False
    assert attrs["createrole"] is False
    assert attrs["createdb"] is True  # bases de test pytest-django


def test_database_owned_by_owner_role(app_conn: psycopg.Connection[Any]) -> None:
    owner = app_conn.execute(
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
    ).fetchone()
    assert owner == (env("RBI_DB_OWNER"),)


def test_backend_never_receives_superuser_password() -> None:
    assert "POSTGRES_SUPERUSER_PASSWORD" not in os.environ
    assert "POSTGRES_PASSWORD" not in os.environ


def test_app_role_cannot_create_objects(app_conn: psycopg.Connection[Any]) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute("CREATE TABLE rbi_forbidden (id int)")


def test_app_role_cannot_connect_to_maintenance_db() -> None:
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        connect("RBI_DB_APP_USER", "RBI_DB_APP_PASSWORD", "postgres")


def test_default_privileges_and_real_rls(
    owner_conn: psycopg.Connection[Any], app_conn: psycopg.Connection[Any]
) -> None:
    """Le rôle applicatif lit/écrit les tables du propriétaire, ne peut pas les modifier,
    et une politique RLS le restreint réellement à l'organisme positionné par SET LOCAL."""
    table = sql.Identifier(f"rbi_infra_check_{uuid.uuid4().hex[:12]}")
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    owner_conn.autocommit = True
    owner_conn.execute(
        sql.SQL("CREATE TABLE {} (id serial PRIMARY KEY, organization_id uuid NOT NULL)").format(table)
    )
    try:
        owner_conn.execute(
            sql.SQL("INSERT INTO {} (organization_id) VALUES (%s), (%s), (%s)").format(table),
            (org_a, org_a, org_b),
        )
        owner_conn.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(table))
        owner_conn.execute(sql.SQL("ALTER TABLE {} FORCE ROW LEVEL SECURITY").format(table))
        owner_conn.execute(
            sql.SQL(
                "CREATE POLICY tenant_isolation ON {} USING "
                "(organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid) "
                "WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)"
            ).format(table)
        )

        count = sql.SQL("SELECT count(*) FROM {}").format(table)
        # Sans contexte : aucune ligne visible (refus par défaut).
        assert app_conn.execute(count).fetchone() == (0,)
        app_conn.rollback()

        with app_conn.transaction():
            app_conn.execute("SELECT set_config('app.current_org', %s, true)", (str(org_a),))
            assert app_conn.execute(count).fetchone() == (2,)
            # Écriture pour un autre organisme refusée par WITH CHECK.
            with pytest.raises(psycopg.errors.InsufficientPrivilege), app_conn.transaction():
                app_conn.execute(
                    sql.SQL("INSERT INTO {} (organization_id) VALUES (%s)").format(table), (org_b,)
                )

        # SET LOCAL : le contexte disparaît à la fin de la transaction (pas de fuite via le pool).
        assert app_conn.execute("SELECT current_setting('app.current_org', true)").fetchone() in {
            ("",),
            (None,),
        }
        assert app_conn.execute(count).fetchone() == (0,)
        app_conn.rollback()

        # Le rôle applicatif ne peut ni désactiver le RLS ni supprimer la table.
        for statement in ("ALTER TABLE {} DISABLE ROW LEVEL SECURITY", "DROP TABLE {}", "TRUNCATE {}"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app_conn.execute(sql.SQL(statement).format(table))
            app_conn.rollback()
    finally:
        owner_conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))


def test_owner_can_create_postgis_test_database(owner_conn: psycopg.Connection[Any]) -> None:
    """pytest-django crée sa base de test avec le rôle propriétaire : PostGIS doit y être présent."""
    name = f"rbi_infra_tmp_{uuid.uuid4().hex[:8]}"
    owner_conn.autocommit = True
    owner_conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with connect("RBI_DB_OWNER", "RBI_DB_OWNER_PASSWORD", name) as conn:
            ext = conn.execute("SELECT extname FROM pg_extension WHERE extname = 'postgis'").fetchone()
            assert ext == ("postgis",)
    finally:
        owner_conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
