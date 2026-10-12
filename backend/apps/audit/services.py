"""Point d'entrée unique des événements d'audit (§9.11 ; ADR 0005 §8, ADR 0009).

P2.3 à P2.6 : JSON structuré sur le journal technique ``rbi.audit``.
P2.7 : chaque événement est en outre ENREGISTRÉ dans le journal append-only chaîné de PostgreSQL
(``audit_auditlog``). Le journal technique reste émis (supervision), mais seul le journal PostgreSQL fait foi.

Règles :
- **contexte serveur uniquement** : organisme, compte et opération plateforme proviennent du périmètre
  validé en cours (``apps.core.db_scope``), l'identifiant de requête et l'IP de
  ``apps.core.request_context``. Aucune valeur fournie par le client n'est acceptée comme preuve ; le RLS de
  la table le revérifie ;
- **catalogue fermé** (``apps.audit.catalog``) et validation stricte des données : aucune clé évoquant un
  secret (mot de passe, code, jeton, cookie, session…), valeurs scalaires courtes, taille bornée ;
- **succès** : enregistré seulement si l'opération est validée (après le COMMIT de la transaction métier) ;
  **refus et échecs** : enregistrés immédiatement et indépendamment, donc conservés même si la transaction
  métier est annulée (connexion d'écriture dédiée, voir ``apps.audit.writer``) ;
- **échec d'écriture** : l'opération en cours échoue (``AuditWriteError``) si l'événement n'a pas pu être
  écrit avant la fin de l'opération ; après un COMMIT, l'événement est consigné en CRITIQUE sur le journal
  technique (limite documentée).
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from typing import Any, Literal

from django.conf import settings
from django.db import connection, transaction

from apps.core.db_scope import current_scope
from apps.core.request_context import current_request_context

from . import writer
from .catalog import ACTIONS, OBJECT_TYPES
from .writer import AuditWriteError, PreparedEvent

logger = logging.getLogger("rbi.audit")

Outcome = Literal["success", "denied", "failure"]
EventScope = Literal["platform", "organization"]

# Même expression que la contrainte SQL (migration audit.0001) : toute clé qui évoque un secret est refusée.
FORBIDDEN_KEY = re.compile(
    r"password|passwd|secret|token|otp|cookie|session|csrf|backup_code|api_key|apikey|private_key|credential",
    re.IGNORECASE,
)
KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
OBJECT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_STRING = 500  # = motif d'une opération plateforme (organizations.services.MAX_REASON_LENGTH)
MAX_ITEMS = 50
MAX_JSON_BYTES = 4000

Scalar = str | int | bool | None


class InvalidAuditEvent(ValueError):
    """Événement non conforme : erreur de programmation, jamais une donnée du client."""


def _scalar(value: object, where: str) -> Scalar:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, uuid.UUID | datetime.date):
        return str(value)
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            raise InvalidAuditEvent(f"{where} : chaîne trop longue")
        return value
    raise InvalidAuditEvent(f"{where} : type non autorisé ({type(value).__name__})")


def _clean(data: dict[str, Any] | None, name: str) -> dict[str, Any] | None:
    """Objet JSON plat : clés sûres, valeurs scalaires ou listes de scalaires."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise InvalidAuditEvent(f"{name} : objet attendu")
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not KEY.match(key) or FORBIDDEN_KEY.search(key):
            raise InvalidAuditEvent(f"{name} : clé refusée ({key!r})")
        if isinstance(value, list | tuple | set | frozenset):
            if len(value) > MAX_ITEMS:
                raise InvalidAuditEvent(f"{name}.{key} : trop d'éléments")
            items = [_scalar(item, f"{name}.{key}") for item in value]
            cleaned[key] = sorted(items, key=str) if isinstance(value, set | frozenset) else items
        else:
            cleaned[key] = _scalar(value, f"{name}.{key}")
    if len(json.dumps(cleaned, ensure_ascii=False).encode()) > MAX_JSON_BYTES:
        raise InvalidAuditEvent(f"{name} : trop volumineux")
    return cleaned


def _uuid(value: object, name: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError as exc:
        raise InvalidAuditEvent(f"{name} : UUID attendu") from exc


def prepare_event(
    action: str,
    *,
    outcome: Outcome,
    actor_id: uuid.UUID | None,
    organization_id: uuid.UUID | None = None,
    scope: EventScope | None = None,
    system: bool = False,
    object_type: str | None = None,
    object_id: object = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> PreparedEvent:
    if action not in ACTIONS:
        raise InvalidAuditEvent(f"action inconnue du catalogue : {action!r}")
    if outcome not in ("success", "denied", "failure"):
        raise InvalidAuditEvent("résultat invalide")
    actor = _uuid(actor_id, "actor_id")
    if actor is not None and system:
        raise InvalidAuditEvent("une action système n'a pas d'acteur utilisateur")
    organization = _uuid(organization_id, "organization_id")
    resolved_scope: EventScope = scope or ("organization" if organization else "platform")
    if resolved_scope == "organization" and organization is None:
        raise InvalidAuditEvent("un événement d'organisme exige l'organisme concerné")
    object_text = None if object_id is None else str(object_id)
    if object_text is not None and (object_type not in OBJECT_TYPES or not OBJECT_ID.match(object_text)):
        raise InvalidAuditEvent("objet invalide")
    if object_type is not None and object_type not in OBJECT_TYPES:
        raise InvalidAuditEvent("type d'objet inconnu")

    database = current_scope()
    request = current_request_context()
    record_ip = getattr(settings, "RBI_AUDIT_RECORD_IP", True)
    return PreparedEvent(
        scope=resolved_scope,
        organization_id=organization,
        actor_type="user" if actor else ("system" if system else "anonymous"),
        actor_id=actor,
        action=action,
        outcome=outcome,
        object_type=object_type,
        object_id=object_text,
        old_value=_clean(old_value, "old_value"),
        new_value=_clean(new_value, "new_value"),
        metadata=_clean(details, "details") or {},
        ip_address=request.ip_address if request and record_ip else None,
        request_id=request.request_id if request else None,
        # Périmètre serveur au moment de l'événement : réappliqué à l'écriture (contrôlé par le RLS).
        context_org=database["current_org"],
        context_user=database["current_user"] or (str(actor) if actor else ""),
        context_platform=database["platform"],
    )


def _log(event: PreparedEvent, *, level: int = logging.INFO, status: str = "recorded") -> None:
    payload = {
        "action": event.action,
        "outcome": event.outcome,
        "scope": event.scope,
        "actor_type": event.actor_type,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "organization_id": str(event.organization_id) if event.organization_id else None,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "details": event.metadata,
        "request_id": str(event.request_id) if event.request_id else None,
        "status": status,
    }
    logger.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True), extra={"audit": payload})


def _persist(event: PreparedEvent) -> None:
    try:
        writer.write(event)
    except Exception as exc:
        _log(event, level=logging.CRITICAL, status="write_failed")
        raise AuditWriteError("Événement d'audit non enregistré.") from exc
    _log(event)


def _persist_after_commit(event: PreparedEvent) -> None:
    """Appelé après le COMMIT : l'opération est déjà validée, un échec ne peut plus l'annuler."""
    try:
        _persist(event)
    except AuditWriteError:
        logger.critical("Événement d'audit perdu après validation de l'opération", exc_info=True)


def record_event(
    action: str,
    *,
    outcome: Outcome,
    actor_id: uuid.UUID | None,
    organization_id: uuid.UUID | None = None,
    scope: EventScope | None = None,
    system: bool = False,
    object_type: str | None = None,
    object_id: object = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Enregistre un événement. ``scope`` par défaut : ``organization`` si un organisme est concerné, sinon
    ``platform`` ; une opération plateforme visant un organisme passe ``scope="platform"``."""
    event = prepare_event(
        action,
        outcome=outcome,
        actor_id=actor_id,
        organization_id=organization_id,
        scope=scope,
        system=system,
        object_type=object_type,
        object_id=object_id,
        old_value=old_value,
        new_value=new_value,
        details=details,
    )
    if writer.mode() == "autonomous" and outcome == "success" and connection.in_atomic_block:
        transaction.on_commit(lambda: _persist_after_commit(event), robust=True)
        return
    _persist(event)


__all__ = ["AuditWriteError", "InvalidAuditEvent", "prepare_event", "record_event"]
