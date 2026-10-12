"""Consultation du journal d'audit (écran 22 ; §7.2 B et F) : chemins dédiés, autorisés et tracés.

- Organisme : permission ``audit.view`` (Administrateur institutionnel, Auditeur) dans le contexte serveur de
  l'utilisateur ; seules les entrées de SON organisme sont lisibles, y compris les opérations plateforme qui
  le concernent.
- Plateforme : ``PlatformScope`` délivré pour ``platform.audit`` (Super Administrateur, Auditeur plateforme) ;
  seules les entrées de portée plateforme sont lisibles, jamais l'activité interne d'un organisme.

La permission est vérifiée par le code PUIS revérifiée par PostgreSQL (RLS + ``rbi_audit_*_reader``). Chaque
consultation, chaque export et chaque vérification d'intégrité est elle-même journalisée (``audit.read``,
``audit.export``, ``audit.verify``). Ces écritures ne déclenchent aucune lecture : pas de boucle.
P2.8 : requête filtrée et paginée, export borné (``AuditQuery``, ``*_page``, ``*_export``).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from django.db.models import Q, QuerySet

from apps.core.db_scope import db_scope
from apps.organizations.platform import PlatformScope, platform_operation
from apps.organizations.tenancy import TenantContext
from apps.users.models import User
from apps.users.rbac import PermissionDeniedError, require_permission

from .integrity import PLATFORM_CHAIN, ChainReport, verify_chain
from .models import AuditLog
from .services import record_event

PLATFORM_AUDIT = "platform.audit"
MAX_LIMIT = 500


def _filtered(
    rows: QuerySet[AuditLog],
    *,
    limit: int,
    before_id: int | None,
    action: str | None,
    since: datetime.datetime | None,
    until: datetime.datetime | None,
) -> list[AuditLog]:
    queryset = rows
    if before_id is not None:
        queryset = queryset.filter(id__lt=before_id)
    if action:
        queryset = queryset.filter(action=action)
    if since is not None:
        queryset = queryset.filter(created_at__gte=since)
    if until is not None:
        queryset = queryset.filter(created_at__lt=until)
    return list(queryset.order_by("-id")[: max(1, min(limit, MAX_LIMIT))])


def _require_org_reader(actor: User, context: TenantContext) -> None:
    if not isinstance(context, TenantContext):
        raise PermissionDeniedError("Vous n'avez pas accès à cette ressource.")
    require_permission(actor, "audit.view", context)


def list_organization_events(
    actor: User,
    context: TenantContext,
    *,
    limit: int = 100,
    before_id: int | None = None,
    action: str | None = None,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
) -> list[AuditLog]:
    _require_org_reader(actor, context)
    with db_scope(current_user=actor.pk, current_org=context.organization_id, auth_email="", platform=""):
        rows = _filtered(
            AuditLog.objects.filter(organization_id=context.organization_id),
            limit=limit,
            before_id=before_id,
            action=action,
            since=since,
            until=until,
        )
    record_event(
        "audit.read",
        outcome="success",
        actor_id=actor.pk,
        organization_id=context.organization_id,
        details={"count": len(rows), "action_filter": action, "before_id": before_id},
    )
    return rows


def verify_organization_chain(actor: User, context: TenantContext) -> ChainReport:
    _require_org_reader(actor, context)
    chain = str(context.organization_id)
    with db_scope(current_user=actor.pk, current_org=context.organization_id, auth_email="", platform=""):
        report = verify_chain(chain)
    record_event(
        "audit.verify",
        outcome="success" if report.intact else "failure",
        actor_id=actor.pk,
        organization_id=context.organization_id,
        object_type="audit_chain",
        object_id=chain,
        details={"checked": report.checked, "intact": report.intact},
    )
    return report


@platform_operation(PLATFORM_AUDIT)
def list_platform_events(
    scope: PlatformScope,
    *,
    limit: int = 100,
    before_id: int | None = None,
    action: str | None = None,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
) -> list[AuditLog]:
    rows = _filtered(
        AuditLog.objects.filter(scope=AuditLog.Scope.PLATFORM),
        limit=limit,
        before_id=before_id,
        action=action,
        since=since,
        until=until,
    )
    record_event(
        "audit.read",
        outcome="success",
        actor_id=scope.actor_id,
        details={"count": len(rows), "action_filter": action, "before_id": before_id},
    )
    return rows


@platform_operation(PLATFORM_AUDIT)
def verify_platform_chain(scope: PlatformScope) -> ChainReport:
    report = verify_chain(PLATFORM_CHAIN)
    record_event(
        "audit.verify",
        outcome="success" if report.intact else "failure",
        actor_id=scope.actor_id,
        object_type="audit_chain",
        object_id=PLATFORM_CHAIN,
        details={"checked": report.checked, "intact": report.intact},
    )
    return report


# --- Requêtes de l'API (P2.8) -----------------------------------------------------------------------

EXPORT_MAX_ROWS = 10_000
EXPORT_BATCH = 1_000


class ExportTooLarge(Exception):
    """Plus de ``EXPORT_MAX_ROWS`` entrées : export refusé (filtres à affiner), jamais tronqué en silence."""

    def __init__(self, count: int) -> None:
        super().__init__(count)
        self.count = count


@dataclass(frozen=True, slots=True)
class AuditQuery:
    """Filtres et tri autorisés (valeurs déjà validées par l'API)."""

    date_from: datetime.datetime | None = None
    date_to: datetime.datetime | None = None
    action: str | None = None  # catégorie (« auth », « auth.mfa ») ou action exacte
    outcome: str | None = None
    actor_id: uuid.UUID | None = None
    object_type: str | None = None
    object_id: str | None = None
    ordering: Literal["-id", "id"] = "-id"

    def apply(self, rows: QuerySet[AuditLog]) -> QuerySet[AuditLog]:
        if self.date_from is not None:
            rows = rows.filter(created_at__gte=self.date_from)
        if self.date_to is not None:
            rows = rows.filter(created_at__lt=self.date_to)
        if self.action:
            rows = rows.filter(Q(action=self.action) | Q(action__startswith=f"{self.action}."))
        if self.outcome:
            rows = rows.filter(outcome=self.outcome)
        if self.actor_id is not None:
            rows = rows.filter(actor_id=self.actor_id)
        if self.object_type:
            rows = rows.filter(object_type=self.object_type)
        if self.object_id:
            rows = rows.filter(object_id=self.object_id)
        return rows.order_by(self.ordering)  # identifiant : ordre total et déterministe

    def describe(self) -> dict[str, Any]:
        """Filtres utilisés, pour l'événement de consultation (valeurs scalaires, sans secret)."""
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "action_filter": self.action,
            "outcome_filter": self.outcome,
            "actor_filter": str(self.actor_id) if self.actor_id else None,
            "object_type_filter": self.object_type,
            "object_id_filter": self.object_id,
            "ordering": self.ordering,
        }


@dataclass(frozen=True, slots=True)
class AuditResult:
    count: int
    rows: list[AuditLog]
    actors: dict[uuid.UUID, str]  # adresse des acteurs LISIBLES dans le périmètre courant (RLS)


def _actor_labels(rows: list[AuditLog]) -> dict[uuid.UUID, str]:
    ids = {row.actor_id for row in rows if row.actor_id}
    return dict(User.objects.filter(pk__in=ids).values_list("pk", "email")) if ids else {}


def _page(rows: QuerySet[AuditLog], query: AuditQuery, offset: int, limit: int) -> AuditResult:
    filtered = query.apply(rows)
    page = list(filtered[offset : offset + limit])
    return AuditResult(filtered.count(), page, _actor_labels(page))


def _export(rows: QuerySet[AuditLog], query: AuditQuery) -> AuditResult:
    filtered = query.apply(rows)
    count = filtered.count()
    if count > EXPORT_MAX_ROWS:
        raise ExportTooLarge(count)
    collected: list[AuditLog] = []
    last: int | None = None
    while len(collected) < count:  # lots successifs par identifiant (jamais un OFFSET croissant)
        batch_rows = filtered
        if last is not None:
            batch_rows = (
                filtered.filter(id__lt=last) if query.ordering == "-id" else filtered.filter(id__gt=last)
            )
        batch = list(batch_rows[:EXPORT_BATCH])
        if not batch:
            break
        collected.extend(batch)
        last = batch[-1].id
    return AuditResult(count, collected, _actor_labels(collected))


def _org_scope(actor: User, context: TenantContext) -> Any:
    return db_scope(current_user=actor.pk, current_org=context.organization_id, auth_email="", platform="")


def organization_page(
    actor: User, context: TenantContext, query: AuditQuery, *, offset: int, limit: int
) -> AuditResult:
    _require_org_reader(actor, context)
    with _org_scope(actor, context):
        result = _page(AuditLog.objects.filter(organization_id=context.organization_id), query, offset, limit)
    record_event(
        "audit.read",
        outcome="success",
        actor_id=actor.pk,
        organization_id=context.organization_id,
        details={"count": result.count, "returned": len(result.rows), "offset": offset, **query.describe()},
    )
    return result


def organization_export(actor: User, context: TenantContext, query: AuditQuery) -> AuditResult:
    _require_org_reader(actor, context)
    try:
        with _org_scope(actor, context):
            result = _export(AuditLog.objects.filter(organization_id=context.organization_id), query)
    except ExportTooLarge as exc:
        record_event(
            "audit.export",
            outcome="denied",
            actor_id=actor.pk,
            organization_id=context.organization_id,
            details={"reason": "too_many_rows", "count": exc.count, **query.describe()},
        )
        raise
    record_event(
        "audit.export",
        outcome="success",
        actor_id=actor.pk,
        organization_id=context.organization_id,
        details={"rows": result.count, "format": "csv", **query.describe()},
    )
    return result


@platform_operation(PLATFORM_AUDIT)
def platform_page(scope: PlatformScope, query: AuditQuery, *, offset: int, limit: int) -> AuditResult:
    result = _page(AuditLog.objects.filter(scope=AuditLog.Scope.PLATFORM), query, offset, limit)
    record_event(
        "audit.read",
        outcome="success",
        actor_id=scope.actor_id,
        details={"count": result.count, "returned": len(result.rows), "offset": offset, **query.describe()},
    )
    return result


@platform_operation(PLATFORM_AUDIT)
def platform_export(scope: PlatformScope, query: AuditQuery) -> AuditResult:
    try:
        result = _export(AuditLog.objects.filter(scope=AuditLog.Scope.PLATFORM), query)
    except ExportTooLarge as exc:
        record_event(
            "audit.export",
            outcome="denied",
            actor_id=scope.actor_id,
            details={"reason": "too_many_rows", "count": exc.count, **query.describe()},
        )
        raise
    record_event(
        "audit.export",
        outcome="success",
        actor_id=scope.actor_id,
        details={"rows": result.count, "format": "csv", **query.describe()},
    )
    return result
