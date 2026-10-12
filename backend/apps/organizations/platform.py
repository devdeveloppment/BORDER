"""Périmètre plateforme : seule porte d'entrée des opérations globales (gestion des organismes).

Une opération globale exige un ``PlatformScope``, délivré uniquement par ``platform_scope``
après vérification :
- acteur authentifié et actif ;
- compte plateforme (aucun organisme de rattachement) : un utilisateur organisationnel
  n'agit jamais globalement ;
- permission RBAC de portée plateforme (P2.4 : ``platform.organizations``, ``platform.institutional_admins``…,
  portées par le rôle SUPER_ADMIN ; voir apps.users.catalog).
Chaque délivrance et chaque refus sont audités.

Le périmètre plateforme ne donne AUCUN accès aux données opérationnelles des organismes
(§7.1 : l'accès exceptionnel relève de la procédure d'accès sous mandat, hors P2.3).
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.audit.services import record_event
from apps.core.db_scope import db_scope

from .exceptions import PlatformAccessDenied

MANAGE_ORGANIZATIONS = "platform.organizations"


@dataclass(frozen=True, slots=True)
class PlatformScope:
    actor_id: uuid.UUID
    permission: str
    purpose: str


def platform_scope(actor: Any, *, purpose: str, permission: str = MANAGE_ORGANIZATIONS) -> PlatformScope:
    actor_id = getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None

    def deny(reason: str) -> PlatformAccessDenied:
        record_event(
            "platform.scope",
            outcome="denied",
            actor_id=actor_id,
            details={"purpose": purpose, "permission": permission, "reason": reason},
        )
        return PlatformAccessDenied("Opération réservée au niveau plateforme.")

    if actor_id is None:
        raise deny("unauthenticated")
    if not actor.is_active:
        raise deny("inactive")
    if getattr(actor, "organization_id", None) is not None:
        raise deny("organization_account")
    from apps.users.rbac import has_permission

    if not has_permission(actor, permission):
        raise deny("missing_permission")

    record_event(
        "platform.scope",
        outcome="success",
        actor_id=actor_id,
        details={"purpose": purpose, "permission": permission},
    )
    return PlatformScope(actor_id=actor_id, permission=permission, purpose=purpose)


def require_scope(scope: object, permission: str = MANAGE_ORGANIZATIONS) -> PlatformScope:
    """En tête de chaque opération globale : seul un PlatformScope issu de ``platform_scope`` est accepté,
    et uniquement pour la permission qui a justifié sa délivrance (moindre privilège)."""
    if not isinstance(scope, PlatformScope):
        record_event("platform.scope", outcome="denied", actor_id=None, details={"reason": "missing_scope"})
        raise PlatformAccessDenied("Opération réservée au niveau plateforme.")
    if scope.permission != permission:
        record_event(
            "platform.scope",
            outcome="denied",
            actor_id=scope.actor_id,
            details={"reason": "wrong_permission", "expected": permission, "granted": scope.permission},
        )
        raise PlatformAccessDenied("Opération réservée au niveau plateforme.")
    return scope


def platform_operation[**P, R](
    permission: str = MANAGE_ORGANIZATIONS,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Décorateur des opérations globales : exige un ``PlatformScope`` délivré pour ``permission`` (1er
    argument)
    et transmet ce périmètre à PostgreSQL (``app.platform``) le temps de l'appel seulement, sans organisme.
    Le résultat doit être entièrement évalué dans la fonction (jamais de QuerySet paresseux renvoyé)."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            scope = require_scope(args[0] if args else None, permission)
            with db_scope(current_user=scope.actor_id, current_org="", auth_email="", platform=permission):
                return func(*args, **kwargs)

        return wrapper

    return decorator
