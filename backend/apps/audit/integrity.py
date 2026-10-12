"""Vérification de l'intégrité des chaînes d'audit (§9.11 « chaînage d'empreintes », écran 22 ; ADR 0009).

Chaque entrée porte ``hash = SHA-256(message canonique v1)``, où le message enchaîne, sous forme
« longueur:valeur; » (« ~; » pour NULL), la version, l'empreinte précédente de la même chaîne et les champs de
l'entrée sous leur forme texte PostgreSQL. Une chaîne par organisme (entrées de portée ``organization``) et
une chaîne plateforme (entrées de portée ``platform``).

Le vérificateur recalcule les empreintes EN PYTHON, indépendamment de la fonction SQL de scellement, et
contrôle : lien avec l'entrée précédente, empreinte de chaque entrée, ordre strictement croissant,
concordance avec la tête de chaîne (dernière entrée, dernière empreinte, longueur : détecte une suppression
en fin de chaîne).

Ce que cela détecte : la modification, l'insertion ou la suppression d'une entrée par quelqu'un qui ne
recalcule pas toute la suite de la chaîne et sa tête. Ce que cela NE garantit PAS : un rôle propriétaire ou
superutilisateur peut réécrire la chaîne entière et recalculer les empreintes. Seul un ancrage externe
régulier de la tête de chaîne (copie hors de la base, hors de portée des administrateurs de la base) permet
de le détecter : la commande ``audit_verify`` affiche les têtes à ancrer ; l'ancrage lui-même est hors
périmètre P2.7.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

from django.db import connection

VERSION = "rbi-audit-v1"
GENESIS = "0" * 64
PLATFORM_CHAIN = "platform"

# Forme texte des champs, identique à celle du déclencheur de scellement (migration audit.0001).
FIELDS_SQL = """
    id::text,
    to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    scope, organization_id::text, actor_type, actor_id::text, action, outcome, object_type, object_id,
    old_value::text, new_value::text, metadata::text, ip_address::text, request_id::text
"""


def netstring(value: str | None) -> str:
    return "~;" if value is None else f"{len(value)}:{value};"


def digest(previous: str, fields: Sequence[str | None]) -> str:
    message = netstring(VERSION) + netstring(previous) + "".join(netstring(f) for f in fields)
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Entry:
    id: int
    fields: tuple[str | None, ...]
    prev_hash: str
    hash: str


@dataclass(frozen=True, slots=True)
class Head:
    last_id: int | None
    last_hash: str
    length: int


@dataclass(slots=True)
class ChainReport:
    chain: str
    checked: int = 0
    head_hash: str = GENESIS
    errors: list[str] = field(default_factory=list)

    @property
    def intact(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "chain": self.chain,
            "intact": self.intact,
            "checked": self.checked,
            "head_hash": self.head_hash,
            "errors": list(self.errors[:20]),
        }


MAX_REPORTED_ERRORS = 100  # mémoire bornée même pour une chaîne entièrement altérée


def _error(report: ChainReport, message: str) -> None:
    if len(report.errors) < MAX_REPORTED_ERRORS:
        report.errors.append(message)


def _walk(report: ChainReport, entries: Iterable[Entry]) -> tuple[str, int]:
    previous_hash, previous_id = GENESIS, 0
    for entry in entries:
        report.checked += 1
        if entry.id <= previous_id:
            _error(report, f"#{entry.id} : ordre non croissant")
        if entry.prev_hash != previous_hash:
            _error(report, f"#{entry.id} : lien rompu avec l'entrée précédente")
        if digest(entry.prev_hash, entry.fields) != entry.hash:
            _error(report, f"#{entry.id} : empreinte invalide (contenu modifié)")
        previous_hash, previous_id = entry.hash, entry.id
    report.head_hash = previous_hash
    return previous_hash, previous_id


def _check_head(report: ChainReport, last: tuple[str, int], head: Head | None) -> None:
    previous_hash, previous_id = last
    if head is None:
        if report.checked:
            _error(report, "tête de chaîne absente")
    elif (head.last_hash, head.length, head.last_id) != (previous_hash, report.checked, previous_id or None):
        _error(report, "tête de chaîne discordante (entrée supprimée ou ajoutée hors scellement)")


def verify_entries(chain: str, entries: Iterable[Entry], head: Head | None) -> ChainReport:
    report = ChainReport(chain=chain)
    _check_head(report, _walk(report, entries), head)
    return report


def _chain_filter(chain: str) -> tuple[str, list[str]]:
    if chain == PLATFORM_CHAIN:
        return "scope = 'platform'", []
    return "scope = 'organization' AND organization_id = %s", [chain]


VERIFY_BATCH = 2000


def _stream(chain: str, batch: int) -> Iterator[Entry]:
    """Entrées de la chaîne par lots successifs (clé : identifiant) : mémoire bornée quelle que soit la
    longueur du journal."""
    where, params = _chain_filter(chain)
    # Tri sur la COLONNE de la table : « ORDER BY id » désignerait la sortie id::text (tri lexicographique).
    query = (
        f"SELECT {FIELDS_SQL}, prev_hash, hash FROM audit_auditlog "  # noqa: S608
        f"WHERE {where} AND audit_auditlog.id > %s ORDER BY audit_auditlog.id LIMIT %s"
    )
    last = 0
    while True:
        with connection.cursor() as cursor:
            cursor.execute(query, [*params, last, batch])
            rows = cursor.fetchall()
        for row in rows:
            yield Entry(int(row[0]), tuple(row[:15]), row[15], row[16])
        if len(rows) < batch:
            return
        last = int(rows[-1][0])


def verify_chain(chain: str, *, batch: int = VERIFY_BATCH) -> ChainReport:
    """Vérifie une chaîne avec la connexion et le périmètre courants : sous le rôle applicatif, le RLS ne rend
    visibles que les chaînes que l'appelant peut lire ; une chaîne invisible apparaît vide et sans tête.

    La tête est lue après le parcours (comme en P2.7) : une entrée ajoutée pendant la vérification peut faire
    conclure à tort à une tête discordante ; une nouvelle vérification lève le doute."""
    report = ChainReport(chain=chain)
    last = _walk(report, _stream(chain, batch))
    with connection.cursor() as cursor:
        cursor.execute("SELECT last_id, last_hash, length FROM audit_chain WHERE chain_key = %s", [chain])
        row = cursor.fetchone()
    _check_head(report, last, Head(row[0], row[1], int(row[2])) if row else None)
    return report


def chain_keys() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT chain_key FROM audit_chain ORDER BY chain_key")
        return [str(row[0]) for row in cursor.fetchall()]
