"""Contexte d'organisme (tenant) : déterminé côté serveur, explicite, jamais implicite.

Principes (spécification interne non publiée §12.3) :
- le contexte provient de l'identité authentifiée (``context_for_user``) ou d'un identifiant transporté
  explicitement par une tâche asynchrone (``context_for_task``), jamais d'un paramètre client ;
- **aucun contexte par défaut** : sans contexte, toute lecture ou écriture de données organisationnelles
  échoue (``TenantContextMissing``) au lieu de renvoyer toutes les lignes ;
- le contexte est porté par une ``ContextVar`` : il est propre au thread / à la tâche asyncio courante
  et restauré à la sortie du bloc ``tenant_context``, même en cas d'exception.

P2.6 : ``tenant_context`` transmet aussi le contexte à PostgreSQL (``app.current_org`` et
``app.current_user``,
portée transactionnelle, voir apps.core.db_scope) ; les politiques RLS appliquent alors le même cloisonnement
au niveau de la base, y compris pour du SQL brut ou ``_base_manager``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from apps.core.db_scope import db_scope, identity_scope

from .exceptions import TenantAccessDenied, TenantContextMissing

if TYPE_CHECKING:
    from apps.users.models import User

ContextSource = Literal["user", "task"]


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Périmètre organisationnel autorisé pour l'opération en cours."""

    organization_id: uuid.UUID
    source: ContextSource
    # Compte authentifié à l'origine du contexte (None pour une tâche) : transmis à PostgreSQL pour les
    # données propres au compte (MFA, profil).
    user_id: uuid.UUID | None = None


_current: ContextVar[TenantContext | None] = ContextVar("rbi_tenant_context", default=None)


def get_current_tenant() -> TenantContext:
    """Contexte courant ; lève ``TenantContextMissing`` s'il n'y en a pas (jamais de valeur par défaut)."""
    context = _current.get()
    if context is None:
        raise TenantContextMissing(
            "Aucun contexte d'organisme : opération sur des données organisationnelles refusée."
        )
    return context


def current_tenant_or_none() -> TenantContext | None:
    """Introspection uniquement (journalisation, tests) ; ne jamais s'en servir pour filtrer des données."""
    return _current.get()


@contextmanager
def tenant_context(context: TenantContext) -> Iterator[TenantContext]:
    if not isinstance(context, TenantContext):
        raise TypeError("tenant_context attend un TenantContext.")
    token = _current.set(context)
    try:
        with db_scope(
            current_org=context.organization_id, current_user=context.user_id, auth_email="", platform=""
        ):
            yield context
    finally:
        _current.reset(token)


def _organization_status(organization_id: uuid.UUID) -> str | None:
    from .models import Organization

    return Organization.objects.filter(pk=organization_id).values_list("status", flat=True).first()


def _require_active_organization(status: str | None) -> None:
    from .models import Organization

    if status is None:
        raise TenantAccessDenied("Organisme inconnu.")
    if status != Organization.Status.ACTIVE:
        # SUSPENDUE : connexions bloquées, aucune ingestion ;
        # EN_ATTENTE / AUTORISÉE / ARCHIVÉE : aucun accès (§9.16).
        raise TenantAccessDenied("Organisme non actif.")


def context_for_user(user: User | Any) -> TenantContext:
    """Contexte d'un utilisateur organisationnel authentifié, actif, dont l'organisme est ACTIVE.

    Les comptes plateforme (sans organisme) n'ont pas de contexte : le Super Administrateur n'accède pas
    aux données opérationnelles (§7.1).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        raise TenantAccessDenied("Utilisateur non authentifié.")
    if not user.is_active:
        raise TenantAccessDenied("Compte désactivé.")
    organization_id = getattr(user, "organization_id", None)
    if organization_id is None:
        raise TenantAccessDenied("Compte plateforme : aucun accès aux données organisationnelles.")
    # Vérification dans le périmètre du seul compte concerné : son organisme est visible, rien d'autre.
    with identity_scope(user.pk):
        status = _organization_status(organization_id)
    _require_active_organization(status)
    return TenantContext(organization_id=organization_id, source="user", user_id=user.pk)


def context_for_task(organization_id: uuid.UUID | str | None) -> TenantContext:
    """Contexte d'une tâche asynchrone, à partir de l'identifiant qu'elle transporte explicitement."""
    if organization_id is None or organization_id == "":
        raise TenantContextMissing("Tâche sans organization_id : exécution refusée.")
    try:
        parsed = (
            organization_id if isinstance(organization_id, uuid.UUID) else uuid.UUID(str(organization_id))
        )
    except ValueError as exc:
        raise TenantAccessDenied("organization_id invalide.") from exc
    with db_scope(current_org=parsed, current_user="", auth_email="", platform=""):
        status = _organization_status(parsed)
    _require_active_organization(status)
    return TenantContext(organization_id=parsed, source="task")
