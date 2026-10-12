"""Vraies connexions ouvertes avec le rôle applicatif (session_user = rbi_app) : cycle de vie du contexte.

Données réellement validées (``transaction=True``) puis effacées par pytest-django. Aucun pool de connexions
n'est configuré (ADR 0008) ; une connexion psycopg réutilisée sur plusieurs transactions reproduit le cas des
connexions persistantes de Django (``CONN_MAX_AGE``) et d'un pool en mode transaction.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from django.conf import settings

from apps.integrations.models import DataSource
from apps.organizations.models import Organization
from apps.organizations.tenancy import TenantContext, tenant_context

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def sources(org_a: Organization, org_b: Organization) -> dict[str, Any]:
    with tenant_context(TenantContext(org_a.pk, "task")):
        a = DataSource.objects.create(name="Source A", source_type="manuelle").pk
    with tenant_context(TenantContext(org_b.pk, "task")):
        b = DataSource.objects.create(name="Source B", source_type="manuelle").pk
    return {"org_a": org_a.pk, "org_b": org_b.pk, "a": a, "b": b}


@pytest.fixture
def app_conn() -> Iterator[psycopg.Connection[Any]]:
    db = settings.DATABASES["default"]
    with psycopg.connect(
        host=str(db["HOST"]),
        port=str(db["PORT"]),
        dbname=str(db["NAME"]),  # base de test
        user=os.environ["RBI_DB_APP_USER"],
        password=os.environ["RBI_DB_APP_PASSWORD"],
    ) as conn:
        yield conn


def org_setting(conn: psycopg.Connection[Any]) -> str:
    row = conn.execute("SELECT coalesce(current_setting('app.current_org', true), '')").fetchone()
    return str(row[0]) if row else ""


def visible(conn: psycopg.Connection[Any]) -> set[Any]:
    return {row[0] for row in conn.execute("SELECT id FROM integrations_datasource").fetchall()}


def test_real_session_is_application_role(app_conn: psycopg.Connection[Any]) -> None:
    app = os.environ["RBI_DB_APP_USER"]
    assert app_conn.execute("SELECT current_user, session_user").fetchone() == (app, app)
    app_conn.rollback()
    for statement in (
        f'SET ROLE "{os.environ["RBI_DB_OWNER"]}"',
        f'SET SESSION AUTHORIZATION "{os.environ["RBI_DB_OWNER"]}"',
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_conn.execute(statement)
        app_conn.rollback()
    app_conn.execute("SET ROLE NONE")  # revient à l'utilisateur de session : rbi_app
    assert app_conn.execute("SELECT current_user").fetchone() == (app,)
    app_conn.rollback()


def test_context_cleared_after_commit(app_conn: psycopg.Connection[Any], sources: dict[str, Any]) -> None:
    with app_conn.transaction():
        app_conn.execute("SELECT set_config('app.current_org', %s, true)", [str(sources["org_a"])])
        assert visible(app_conn) == {sources["a"]}
    assert org_setting(app_conn) == ""
    assert visible(app_conn) == set()


def test_context_cleared_after_rollback(app_conn: psycopg.Connection[Any], sources: dict[str, Any]) -> None:
    app_conn.execute("SELECT set_config('app.current_org', %s, true)", [str(sources["org_a"])])
    assert visible(app_conn) == {sources["a"]}
    app_conn.rollback()
    assert org_setting(app_conn) == ""
    assert visible(app_conn) == set()
    app_conn.rollback()


def test_failed_transaction_leaves_no_context(
    app_conn: psycopg.Connection[Any], sources: dict[str, Any]
) -> None:
    app_conn.execute("SELECT set_config('app.current_org', %s, true)", [str(sources["org_a"])])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_conn.execute(
            "INSERT INTO integrations_datasource (id, organization_id, name, source_type, legal_basis_ref, "
            "status, "
            "created_at, updated_at) VALUES (gen_random_uuid(), %s, 'X', 'manuelle', '', 'active', now(), "
            "now())",
            [str(sources["org_b"])],
        )
    app_conn.rollback()
    assert org_setting(app_conn) == ""
    assert visible(app_conn) == set()
    app_conn.rollback()


def test_reused_connection_switching_a_to_b(
    app_conn: psycopg.Connection[Any], sources: dict[str, Any]
) -> None:
    for org, own in (
        (sources["org_a"], sources["a"]),
        (sources["org_b"], sources["b"]),
        (sources["org_a"], sources["a"]),
    ):
        with app_conn.transaction():
            app_conn.execute("SELECT set_config('app.current_org', %s, true)", [str(org)])
            assert visible(app_conn) == {own}  # jamais une ligne de l'organisme précédent
    assert visible(app_conn) == set()


def test_set_local_outside_transaction_has_no_effect(
    app_conn: psycopg.Connection[Any], sources: dict[str, Any]
) -> None:
    """En autocommit, SET LOCAL meurt avec son instruction : d'où l'ouverture d'une transaction par
    db_scope."""
    app_conn.autocommit = True
    app_conn.execute("SELECT set_config('app.current_org', %s, true)", [str(sources["org_a"])])
    assert visible(app_conn) == set()


def test_rbi_never_sets_a_session_level_context() -> None:
    """Analyse statique : aucun ``set_config(..., false)`` ni ``SET app.…`` hors ``SET LOCAL`` dans le
    code."""
    root = Path(settings.BASE_DIR) / "apps"
    offenders = []
    for path in root.rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"set_config\([^)]*,\s*false\)", text, re.I) or re.search(
            r"\bSET\s+(SESSION\s+)?app\.", text
        ):
            offenders.append(path.name)
    assert offenders == []
