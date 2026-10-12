"""Chaînage SHA-256 et détection d'altération (§9.11 ; ADR 0009).

Les altérations sont simulées en PROPRIÉTAIRE, déclencheurs d'immuabilité désactivés, dans la transaction du
test (annulée ensuite) : c'est exactement ce que peut faire un administrateur de la base, et ce que le
chaînage doit révéler — sauf réécriture complète, détectable seulement par une tête de chaîne ancrée hors de
la base.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection

from apps.audit.integrity import FIELDS_SQL, GENESIS, Entry, Head, digest, verify_chain, verify_entries
from apps.audit.services import record_event
from apps.core.request_context import request_context
from apps.organizations.models import Organization
from apps.users.models import User
from conftest import owner

pytestmark = pytest.mark.django_db

TRICKY = 'é€ ; 3:x; ~; " \\ \n\t \u0001 «»'


@pytest.fixture
def chain(admin_a: User, org_a: Organization) -> Iterator[list[int]]:
    """Quatre entrées dans la chaîne de l'organisme A, avec des contenus délicats à sérialiser."""
    with request_context(request_id=uuid.uuid4(), ip_address="2001:db8::1"):
        record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
        record_event(
            "auth.mfa.disable",
            outcome="denied",
            actor_id=admin_a.pk,
            organization_id=org_a.pk,
            details={"reason": TRICKY, "items": [1, True, None, "a;b"]},
        )
    record_event(
        "user.role.assign",
        outcome="denied",
        actor_id=admin_a.pk,
        organization_id=org_a.pk,
        object_type="user",
        object_id=admin_a.pk,
        old_value={"role": None},
        new_value={"role": "AGENT"},
    )
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    with owner(), connection.cursor() as cursor:
        cursor.execute("SELECT id FROM audit_auditlog WHERE organization_id = %s ORDER BY id", [org_a.pk])
        yield [row[0] for row in cursor.fetchall()]


def tamper(sql: str, params: list[Any] | None = None) -> None:
    """Action d'un administrateur de la base : déclencheurs désactivés le temps de l'altération."""
    with owner(), connection.cursor() as cursor:
        cursor.execute("ALTER TABLE audit_auditlog DISABLE TRIGGER rbi_audit_immutable")
        cursor.execute("ALTER TABLE audit_chain DISABLE TRIGGER rbi_audit_immutable")
        cursor.execute(sql, params or [])
        cursor.execute("ALTER TABLE audit_auditlog ENABLE TRIGGER rbi_audit_immutable")
        cursor.execute("ALTER TABLE audit_chain ENABLE TRIGGER rbi_audit_immutable")


def verify(org: Organization) -> list[str]:
    with owner():
        return verify_chain(str(org.pk)).errors


def test_python_verifier_matches_postgresql_sealing(chain: list[int], org_a: Organization) -> None:
    with owner():
        report = verify_chain(str(org_a.pk))
    assert report.intact, report.errors
    assert report.checked == len(chain) == 4


def test_verification_does_not_depend_on_session_timezone(
    chain: list[int], org_a: Organization, admin_a: User
) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'Pacific/Kiritimati'")
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'America/Anchorage'")
    assert verify(org_a) == []


def test_chain_crossing_a_digit_boundary_is_verified(admin_a: User, org_a: Organization) -> None:
    """Identifiants 9…9 puis 10…0 dans la même chaîne : le vérificateur doit trier numériquement (un tri sur
    la forme texte de l'identifiant les inverserait — défaut réel corrigé pendant P2.7)."""
    with owner(), connection.cursor() as cursor:
        cursor.execute("SELECT nextval('audit_auditlog_id_seq')")
        current = int(cursor.fetchone()[0])
        # La séquence n'est pas transactionnelle : saut vers le prochain changement de nombre de chiffres.
        cursor.execute("SELECT setval('audit_auditlog_id_seq', %s)", [10 ** len(str(current + 2)) - 2])
    for _ in range(4):
        record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    with owner(), connection.cursor() as cursor:
        cursor.execute("SELECT id FROM audit_auditlog WHERE organization_id = %s ORDER BY id", [org_a.pk])
        ids = [row[0] for row in cursor.fetchall()]
    assert len({len(str(i)) for i in ids}) == 2  # le changement de longueur est bien franchi
    assert verify(org_a) == []


def test_chains_are_independent_per_organization(
    chain: list[int], org_a: Organization, org_b: Organization, admin_b: User
) -> None:
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_b.pk, organization_id=org_b.pk)
    with owner(), connection.cursor() as cursor:
        cursor.execute("SELECT prev_hash FROM audit_auditlog WHERE organization_id = %s", [org_b.pk])
        assert cursor.fetchall() == [(GENESIS,)]  # première entrée de B : rien de A n'y est lié
    assert verify(org_a) == [] and verify(org_b) == []


def test_modified_content_is_detected(chain: list[int], org_a: Organization) -> None:
    tamper("UPDATE audit_auditlog SET outcome = 'success' WHERE id = %s", [chain[1]])
    assert verify(org_a) == [f"#{chain[1]} : empreinte invalide (contenu modifié)"]


def test_modified_json_is_detected(chain: list[int], org_a: Organization) -> None:
    tamper('UPDATE audit_auditlog SET new_value = \'{"role": "ORG_ADMIN"}\' WHERE id = %s', [chain[2]])
    assert verify(org_a) == [f"#{chain[2]} : empreinte invalide (contenu modifié)"]


def test_modified_timestamp_is_detected(chain: list[int], org_a: Organization) -> None:
    tamper("UPDATE audit_auditlog SET created_at = created_at - interval '1 day' WHERE id = %s", [chain[0]])
    assert verify(org_a) == [f"#{chain[0]} : empreinte invalide (contenu modifié)"]


def test_deleted_entry_is_detected(chain: list[int], org_a: Organization) -> None:
    tamper("DELETE FROM audit_auditlog WHERE id = %s", [chain[1]])
    errors = verify(org_a)
    assert f"#{chain[2]} : lien rompu avec l'entrée précédente" in errors
    assert any("tête de chaîne discordante" in e for e in errors)


def test_deleted_tail_is_detected_by_the_chain_head(chain: list[int], org_a: Organization) -> None:
    tamper("DELETE FROM audit_auditlog WHERE id = %s", [chain[-1]])
    assert verify(org_a) == ["tête de chaîne discordante (entrée supprimée ou ajoutée hors scellement)"]


def test_rehashed_entry_breaks_the_next_link(chain: list[int], org_a: Organization) -> None:
    """Contenu modifié ET empreinte recalculée pour cette seule entrée : le lien suivant se rompt."""
    tamper("UPDATE audit_auditlog SET outcome = 'success', hash = repeat('a', 64) WHERE id = %s", [chain[1]])
    errors = verify(org_a)
    assert f"#{chain[2]} : lien rompu avec l'entrée précédente" in errors


def test_full_rewrite_is_only_detected_by_an_external_anchor(chain: list[int], org_a: Organization) -> None:
    """LIMITE : un administrateur qui réécrit une entrée, recalcule TOUTE la suite et la tête rend la chaîne
    cohérente. Seule une tête ancrée hors de la base avant l'altération révèle la réécriture."""
    with owner():
        anchored = verify_chain(str(org_a.pk)).head_hash  # ancrage externe simulé
    tamper("UPDATE audit_auditlog SET outcome = 'success' WHERE id = %s", [chain[1]])
    query = f"SELECT {FIELDS_SQL} FROM audit_auditlog WHERE organization_id = %s ORDER BY audit_auditlog.id"  # noqa: S608
    with owner(), connection.cursor() as cursor:
        cursor.execute(query, [org_a.pk])
        rows = cursor.fetchall()
    previous = GENESIS
    for row in rows:
        new_hash = digest(previous, row)
        tamper(
            "UPDATE audit_auditlog SET prev_hash = %s, hash = %s WHERE id = %s",
            [previous, new_hash, int(row[0])],
        )
        previous = new_hash
    tamper("UPDATE audit_chain SET last_hash = %s WHERE chain_key = %s", [previous, str(org_a.pk)])
    with owner():
        report = verify_chain(str(org_a.pk))
    assert report.intact  # cohérente…
    assert report.head_hash != anchored  # …mais différente de la tête ancrée : réécriture révélée


# --- Vérificateur pur (sans base) ----------------------------------------------------------------------


def _entries(n: int) -> list[Entry]:
    entries, previous = [], GENESIS
    for i in range(1, n + 1):
        fields = (
            str(i),
            "2026-10-09T00:00:00.000000Z",
            "platform",
            None,
            "system",
            None,
            "audit.verify",
            "success",
            None,
            None,
            None,
            None,
            "{}",
            None,
            None,
        )
        current = digest(previous, fields)
        entries.append(Entry(i, fields, previous, current))
        previous = current
    return entries


def test_pure_verifier_accepts_a_valid_chain() -> None:
    entries = _entries(3)
    assert verify_entries("platform", entries, Head(3, entries[-1].hash, 3)).intact


def test_pure_verifier_detects_reordering_and_missing_head() -> None:
    entries = _entries(3)
    swapped = [entries[0], entries[2], entries[1]]
    assert not verify_entries("platform", swapped, Head(3, entries[-1].hash, 3)).intact
    assert verify_entries("platform", entries, None).errors == ["tête de chaîne absente"]


def test_netstring_encoding_is_unambiguous() -> None:
    """« a;b » en un champ ≠ « a » et « b » en deux champs ; NULL ≠ chaîne « ~ »."""
    assert digest(GENESIS, ["a;b"]) != digest(GENESIS, ["a", "b"])
    assert digest(GENESIS, [None]) != digest(GENESIS, ["~"])
    assert digest(GENESIS, [""]) != digest(GENESIS, [None])
