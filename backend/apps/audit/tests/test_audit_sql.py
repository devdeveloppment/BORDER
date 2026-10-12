"""Protections PostgreSQL du journal d'audit, éprouvées en SQL direct (P2.7, ADR 0009).

Le corps de chaque test s'exécute sous ``rbi_app`` (conftest) : privilèges, RLS, contraintes et déclencheurs
sont ceux de l'API et du worker. ``owner()`` sert à préparer et à vérifier (rôle propriétaire, hors RLS), et à
montrer ce que les déclencheurs bloquent même pour lui.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from apps.organizations.models import Organization
from apps.users.models import User
from conftest import create_user, grant_role, owner

pytestmark = pytest.mark.django_db


def scope(org: object = "", user: object = "", platform: str = "") -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.current_org', %s, true), set_config('app.current_user', %s, true), "
            "set_config('app.auth_email', '', true), set_config('app.platform', %s, true)",
            [str(org or ""), str(user or ""), platform],
        )


def insert(**values: Any) -> None:
    row: dict[str, Any] = {
        "scope": "organization",
        "actor_type": "system",
        "action": "audit.verify",
        "outcome": "success",
        "metadata": "{}",
    }
    row.update(values)
    columns = ", ".join(row)
    placeholders = ", ".join(
        "%s::jsonb" if k in ("metadata", "old_value", "new_value") else "%s" for k in row
    )
    query = f"INSERT INTO audit_auditlog ({columns}) VALUES ({placeholders})"  # noqa: S608
    with connection.cursor() as cursor:
        cursor.execute(query, list(row.values()))


def rejected(sql: str, params: list[Any] | None = None) -> str:
    """Exécute ``sql`` dans un point de sauvegarde et renvoie le message d'erreur PostgreSQL (échec
    attendu)."""
    with pytest.raises(DatabaseError) as excinfo, transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(sql, params or [])
    return str(excinfo.value)


def rejected_insert(**values: Any) -> str:
    with pytest.raises(DatabaseError) as excinfo, transaction.atomic():
        insert(**values)
    return str(excinfo.value)


def all_rows() -> list[dict[str, Any]]:
    with owner(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, scope, organization_id, actor_id, action, prev_hash, hash, created_at "
            "FROM audit_auditlog ORDER BY id"
        )
        names = [c.name for c in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def visible_ids() -> set[int]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM audit_auditlog")
        return {row[0] for row in cursor.fetchall()}


@pytest.fixture
def world(
    org_a: Organization, org_b: Organization, admin_a: User, admin_b: User, user_a: User
) -> dict[str, Any]:
    """Une entrée par organisme et une entrée plateforme, scellées par PostgreSQL (insérées en
    propriétaire)."""
    platform = create_user("auditeur.plateforme@plateforme.rbi.test")
    grant_role(platform, "AUDITOR")
    with owner():
        before = {row["id"] for row in all_rows()}
        insert(organization_id=str(org_a.pk), action="user.create")
        insert(organization_id=str(org_b.pk), action="user.create")
        insert(scope="platform", action="platform.scope")
        insert(scope="platform", organization_id=str(org_a.pk), action="organization.transition")
        rows = [row for row in all_rows() if row["id"] not in before]
    ids = [row["id"] for row in rows]
    return {
        "a": ids[0],
        "b": ids[1],
        "platform": ids[2],
        "platform_about_a": ids[3],
        "org_a": org_a.pk,
        "org_b": org_b.pk,
        "admin_a": admin_a.pk,
        "admin_b": admin_b.pk,
        "agent_a": user_a.pk,
        "platform_auditor": platform.pk,
    }


@pytest.fixture
def mine(world: dict[str, Any]) -> Iterator[set[int]]:
    """Identifiants créés par ce test (le journal de la base de test peut contenir d'autres entrées)."""
    yield {world["a"], world["b"], world["platform"], world["platform_about_a"]}


# --- Scellement par PostgreSQL ------------------------------------------------------------------------


def test_application_role_inserts_and_postgresql_seals(world: dict[str, Any], org_a: Organization) -> None:
    scope(org=org_a.pk, user=world["admin_a"])
    insert(
        organization_id=str(org_a.pk), actor_type="user", actor_id=str(world["admin_a"]), action="user.create"
    )
    newest = all_rows()[-1]
    assert newest["actor_id"] == world["admin_a"] and newest["organization_id"] == org_a.pk
    assert newest["created_at"] is not None and len(newest["hash"]) == 64
    with owner(), connection.cursor() as cursor:  # lien avec l'entrée précédente de la MÊME chaîne
        cursor.execute("SELECT hash FROM audit_auditlog WHERE id = %s", [world["a"]])
        assert cursor.fetchone() == (newest["prev_hash"],)
        cursor.execute("SELECT last_id, last_hash FROM audit_chain WHERE chain_key = %s", [str(org_a.pk)])
        assert cursor.fetchone() == (newest["id"], newest["hash"])


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("id", 1),
        ("created_at", "2000-01-01T00:00:00Z"),
        ("hash", "0" * 64),
        ("prev_hash", "0" * 64),
    ],
)
def test_sealing_columns_cannot_be_supplied(column: str, value: object) -> None:
    """Identifiant, horodatage et empreintes sont posés par PostgreSQL, jamais par l'application."""
    assert "permission denied" in rejected_insert(scope="platform", **{column: value})


# --- Insertion seule ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_auditlog SET outcome = 'failure'",
        "UPDATE audit_auditlog SET metadata = '{}'::jsonb WHERE id > 0",
        "DELETE FROM audit_auditlog",
        "TRUNCATE audit_auditlog",
        "UPDATE audit_chain SET last_hash = repeat('0', 64)",
        "DELETE FROM audit_chain",
        "TRUNCATE audit_chain",
        "INSERT INTO audit_chain (chain_key, last_hash) VALUES ('forged', repeat('0', 64))",
        "SELECT nextval('audit_auditlog_id_seq')",
        "SELECT setval('audit_auditlog_id_seq', 1)",
        "ALTER TABLE audit_auditlog DISABLE TRIGGER rbi_audit_immutable",
        "DROP TABLE audit_auditlog",
        "SELECT rbi_audit_seal()",
    ],
)
def test_application_role_cannot_alter_the_journal(world: dict[str, Any], statement: str) -> None:
    scope(org=world["org_a"], user=world["admin_a"])  # même avec un contexte valide d'administrateur
    message = rejected(statement)
    assert "permission denied" in message or "must be owner" in message, message


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_auditlog SET outcome = 'failure' WHERE id = %s",
        "DELETE FROM audit_auditlog WHERE id = %s",
        "TRUNCATE audit_auditlog",
        "UPDATE audit_chain SET length = 0",
        "DELETE FROM audit_chain",
    ],
)
def test_triggers_block_even_the_owner(world: dict[str, Any], statement: str) -> None:
    """Défense en profondeur : même le propriétaire (migrations, maintenance) ne modifie pas le journal par
    accident. Ce n'est pas une barrière contre lui : il peut désactiver les déclencheurs (ADR 0009)."""
    with owner():
        message = rejected(statement, [world["a"]] if "%s" in statement else [])
    assert "insertion seule" in message, message


# --- Lecture : isolation et absence de lecture globale ---------------------------------------------------


def test_no_context_reads_nothing(world: dict[str, Any]) -> None:
    assert visible_ids() == set()
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM audit_chain")
        assert cursor.fetchone() == (0,)


def test_organization_reader_sees_only_its_organization(world: dict[str, Any], mine: set[int]) -> None:
    scope(org=world["org_a"], user=world["admin_a"])
    assert visible_ids() & mine == {world["a"], world["platform_about_a"]}
    with connection.cursor() as cursor:
        cursor.execute("SELECT chain_key FROM audit_chain")
        assert {row[0] for row in cursor.fetchall()} == {str(world["org_a"])}


def test_organization_member_without_audit_permission_reads_nothing(world: dict[str, Any]) -> None:
    grant_role(_user(world["agent_a"]), "AGENT")
    scope(org=world["org_a"], user=world["agent_a"])
    assert visible_ids() == set()


def test_forged_organization_context_reads_nothing(world: dict[str, Any]) -> None:
    """Contexte d'un autre organisme avec l'identité d'un administrateur de A : la permission est revérifiée
    en SQL pour le couple (compte, organisme)."""
    scope(org=world["org_b"], user=world["admin_a"])
    assert visible_ids() == set()
    scope(org=world["org_a"], user=str(uuid.uuid4()))
    assert visible_ids() == set()


def test_platform_reader_sees_only_platform_entries(world: dict[str, Any], mine: set[int]) -> None:
    scope(user=world["platform_auditor"], platform="platform.audit")
    assert visible_ids() & mine == {world["platform"], world["platform_about_a"]}


@pytest.mark.parametrize(
    ("user_key", "platform"),
    [
        ("platform_auditor", ""),  # pas d'opération plateforme délivrée
        ("platform_auditor", "platform.organizations"),  # autre permission plateforme
        ("admin_a", "platform.audit"),  # compte d'organisme avec une variable falsifiée
    ],
)
def test_platform_reading_requires_the_audit_permission(
    world: dict[str, Any], user_key: str, platform: str
) -> None:
    scope(user=world[user_key], platform=platform)
    assert visible_ids() & {world["platform"], world["platform_about_a"]} == set()


def test_malformed_context_is_an_error_not_an_access(world: dict[str, Any]) -> None:
    with pytest.raises(DatabaseError) as excinfo, transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.current_org', 'pas-un-uuid', true)")
        cursor.execute("SELECT count(*) FROM audit_auditlog")
    assert "invalid input syntax for type uuid" in str(excinfo.value)


# --- Écriture : attribution limitée au contexte serveur -------------------------------------------------


def test_event_cannot_be_attributed_to_another_organization(world: dict[str, Any]) -> None:
    scope(org=world["org_a"], user=world["admin_a"])
    message = rejected_insert(
        organization_id=str(world["org_b"]), actor_type="user", actor_id=str(world["admin_a"])
    )
    assert "row-level security" in message


def test_event_cannot_be_attributed_to_another_actor(world: dict[str, Any]) -> None:
    scope(org=world["org_a"], user=world["admin_a"])
    message = rejected_insert(
        organization_id=str(world["org_a"]), actor_type="user", actor_id=str(world["admin_b"])
    )
    assert "row-level security" in message


def test_organization_event_without_context_is_refused(world: dict[str, Any]) -> None:
    assert "row-level security" in rejected_insert(organization_id=str(world["org_a"]))


def test_identified_account_attributes_to_its_own_organization_only(world: dict[str, Any]) -> None:
    """Avant authentification complète (compte identifié, aucun contexte d'organisme) : seul l'organisme du
    compte est accepté."""
    scope(user=world["admin_a"])
    insert(organization_id=str(world["org_a"]), actor_type="user", actor_id=str(world["admin_a"]))
    message = rejected_insert(
        organization_id=str(world["org_b"]), actor_type="user", actor_id=str(world["admin_a"])
    )
    assert "row-level security" in message


def test_platform_event_about_an_organization_requires_a_platform_operation(world: dict[str, Any]) -> None:
    scope(user=world["platform_auditor"], platform="platform.audit")
    message = rejected_insert(scope="platform", organization_id=str(world["org_a"]))
    assert "row-level security" in message
    scope(platform="platform.organizations")
    insert(scope="platform", organization_id=str(world["org_a"]), action="organization.transition")


def test_anonymous_platform_event_is_accepted(world: dict[str, Any]) -> None:
    """Échec de connexion sans compte identifié : aucun contexte, aucun organisme, acteur anonyme."""
    insert(scope="platform", actor_type="anonymous", action="auth.login", outcome="failure")


# --- Contenu : structure et absence de secrets (contraintes SQL) ----------------------------------------


@pytest.mark.parametrize(
    "values",
    [
        {"metadata": json.dumps({"password": "Fictif-2026"})},
        {"metadata": json.dumps({"reason": "x", "detail": {"api_token": "abc"}})},
        {"metadata": json.dumps({"TOTP_secret": "JBSWY3DPEHPK3PXP"})},
        {"metadata": json.dumps({"items": [{"backup_code": "1234-5678"}]})},
        {"old_value": json.dumps({"session_key": "s"})},
        {"new_value": json.dumps({"csrftoken": "t"})},
        {"metadata": json.dumps({"cookie": "rbi_session=x"})},
    ],
)
def test_secret_keys_are_refused_by_postgresql(values: dict[str, str]) -> None:
    assert "violates check constraint" in rejected_insert(scope="platform", **values)


@pytest.mark.parametrize(
    "values",
    [
        {"metadata": "[]"},
        {"metadata": json.dumps({"blob": "".join(uuid.uuid4().hex for _ in range(200))})},
        {"action": "Login"},
        {"action": "auth"},
        {"action": "auth.login; DROP TABLE x"},
        {"actor_type": "user"},  # acteur « utilisateur » sans identifiant
        {"actor_type": "system", "actor_id": str(uuid.uuid4())},
        {"scope": "organization"},  # événement d'organisme sans organisme
        {"scope": "tenant"},
        {"outcome": "ok"},
        {"object_id": "x"},  # identifiant d'objet sans type
        {"object_type": "user", "object_id": "a b"},
    ],
)
def test_malformed_events_are_refused_by_postgresql(values: dict[str, Any]) -> None:
    """Contraintes de structure, éprouvées en propriétaire : elles s'appliquent quel que soit le rôle (le RLS,
    vérifié avant elles pour le rôle applicatif, masquerait sinon certaines d'entre elles)."""
    values.setdefault("scope", "platform")
    with owner():
        assert "violates check constraint" in rejected_insert(**values)


def _user(pk: uuid.UUID) -> User:
    with owner():
        return User.objects.get(pk=pk)
