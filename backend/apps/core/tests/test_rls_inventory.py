"""L'état réel de PostgreSQL correspond exactement à l'inventaire de sécurité (apps.core.rls_inventory)."""

from __future__ import annotations

import os

import pytest
from django.apps import apps
from django.db import connection

from apps.core.rls_inventory import DEFINER_FUNCTIONS, INVENTORY, TRIGGER_DEFINER_FUNCTIONS
from apps.organizations.models import TenantScopedModel

# Lecture du catalogue système : avec le rôle propriétaire de la connexion de test.
pytestmark = [pytest.mark.django_db, pytest.mark.db_owner]

APP = os.environ["RBI_DB_APP_USER"]
OWNER = os.environ["RBI_DB_OWNER"]


def _tables() -> dict[str, tuple[str, bool, bool]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, pg_get_userbyid(c.relowner), c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')"
        )
        return {name: (owner, rls, force) for name, owner, rls, force in cursor.fetchall()}


def _policies(table: str) -> dict[str, tuple[str, str | None, str | None, bool]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT policyname, cmd, qual, with_check, permissive = 'PERMISSIVE' FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename = %s",
            [table],
        )
        return {
            name: (cmd, qual, check, permissive) for name, cmd, qual, check, permissive in cursor.fetchall()
        }


def _privilege(table: str, privilege: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(%s, %s, %s)", [APP, f"public.{table}", privilege])
        row = cursor.fetchone()
    return bool(row and row[0])


def _column_privileges(table: str, privilege: str) -> set[str]:
    """Colonnes sur lesquelles le rôle applicatif détient ``privilege`` (au niveau de la colonne ou de la
    table)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT a.attname FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attnum > 0 "
            "AND NOT a.attisdropped AND has_column_privilege(%s, a.attrelid, a.attnum, %s)",
            [f"public.{table}", APP, privilege],
        )
        return {row[0] for row in cursor.fetchall()}


def test_every_table_is_inventoried() -> None:
    """Une table créée sans être classée (et donc sans décision d'isolation) fait échouer la suite."""
    assert set(_tables()) == set(INVENTORY)


def test_every_tenant_model_is_protected() -> None:
    tenant_tables = {
        model._meta.db_table
        for model in apps.get_models()
        if issubclass(model, TenantScopedModel) and not model._meta.abstract
    }
    assert tenant_tables, "aucun modèle organisationnel trouvé"
    for table in tenant_tables:
        entry = INVENTORY[table]
        assert entry.category == "tenant" and entry.rls and entry.organization_column == "organization_id", (
            table
        )
        policies = _policies(table)
        assert any(
            cmd == "ALL" and "rbi_current_org()" in (qual or "") and "rbi_current_org()" in (check or "")
            for cmd, qual, check, _ in policies.values()
        ), table


@pytest.mark.parametrize("table", sorted(INVENTORY))
def test_table_matches_inventory(table: str) -> None:
    entry = INVENTORY[table]
    owner, rls, force = _tables()[table]
    if entry.category != "extension":
        assert owner == OWNER  # le rôle applicatif ne possède aucune table
    assert rls is entry.rls, "RLS"
    assert force is False  # choix documenté (ADR 0008) : le propriétaire est le rôle de maintenance
    assert set(_policies(table)) == entry.policies
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _privilege(table, privilege) is (privilege in entry.app_privileges), privilege
    if entry.insert_columns:  # INSERT accordé colonne par colonne, jamais sur les colonnes de scellement
        assert "INSERT" not in entry.app_privileges
        assert _column_privileges(table, "INSERT") == entry.insert_columns
    # Aucun privilège par colonne caché derrière un refus au niveau de la table.
    if "UPDATE" not in entry.app_privileges:
        assert _column_privileges(table, "UPDATE") == set()
    if not entry.insert_columns and "INSERT" not in entry.app_privileges:
        assert _column_privileges(table, "INSERT") == set()
    assert _column_privileges(table, "REFERENCES") == set()
    for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
        assert _privilege(table, privilege) is False, privilege


def test_no_permissive_catch_all_policy() -> None:
    """Aucune politique « tout autoriser » : chaque condition dépend d'un périmètre ou d'un état précis."""
    for table, entry in INVENTORY.items():
        for name, (_, qual, check, permissive) in _policies(table).items():
            assert permissive, name
            for expression in (qual, check):
                assert expression is None or expression.strip("() ").lower() != "true", name
        assert entry.rls or not entry.policies


def test_every_granted_command_is_governed_by_a_policy() -> None:
    """Sur une table protégée, chaque commande accordée au rôle applicatif est encadrée par une politique ;
    les autres sont refusées deux fois (privilège retiré, aucune politique)."""
    for table, entry in INVENTORY.items():
        if not entry.rls:
            continue
        commands = {cmd for cmd, _, _, _ in _policies(table).values()}
        granted = set(entry.app_privileges) | ({"INSERT"} if entry.insert_columns else set())
        for privilege in granted:
            assert "ALL" in commands or privilege in commands, (table, privilege)


def test_definer_functions_are_restricted() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.proname, pg_get_userbyid(p.proowner), p.proconfig, "
            "has_function_privilege('public', p.oid, 'EXECUTE'), has_function_privilege(%s, p.oid, "
            "'EXECUTE') "
            "FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef",
            [APP],
        )
        rows = {name: (owner, config, public, app) for name, owner, config, public, app in cursor.fetchall()}
    assert set(rows) == DEFINER_FUNCTIONS | TRIGGER_DEFINER_FUNCTIONS
    for name, (owner, config, public_exec, app_exec) in rows.items():
        assert owner == OWNER, name
        assert config and any(c.startswith("search_path=") for c in config), name  # pas de détournement
        assert public_exec is False, name
        assert app_exec is (name in DEFINER_FUNCTIONS), name  # fonction de déclencheur : jamais appelable


def test_roles_cannot_bypass_rls() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE "
            "rolname = %s",
            [APP],
        )
        assert cursor.fetchone() == (APP, False, False, False, False)
        cursor.execute(
            "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = %s",
            [APP],
        )
        assert cursor.fetchone() == (0,)  # rbi_app n'est membre d'aucun rôle
        cursor.execute(
            "SELECT m.inherit_option, m.set_option, m.admin_option FROM pg_auth_members m "
            "JOIN pg_roles g ON g.oid = m.roleid JOIN pg_roles u ON u.oid = m.member "
            "WHERE g.rolname = %s AND u.rolname = %s",
            [APP, OWNER],
        )
        # Le propriétaire peut endosser rbi_app (tests) sans en hériter les droits ni l'administrer.
        assert cursor.fetchone() == (False, True, False)
