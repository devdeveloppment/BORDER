"""Cycle de vie des organismes (§9.16) et file des demandes d'accès (écran 5).

Toute écriture passe par ces services. Les opérations de gestion exigent un ``PlatformScope``
(voir platform.py) et sont auditées. Transitions autorisées :

    EN_ATTENTE ──authorize──► AUTORISÉE ──activate──► ACTIVE ⇄ SUSPENDUE (suspend / reactivate)
         └──────────────── archive ─────────────────────┴──────────┴──► ARCHIVÉE (définitif)
"""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.audit.services import record_event

from .exceptions import InvalidTransition
from .models import AccessRequest, Organization, OrganizationAuthorization
from .platform import PlatformScope, platform_operation, require_scope

Status = Organization.Status

TRANSITIONS: dict[str, frozenset[str]] = {
    Status.EN_ATTENTE: frozenset({Status.AUTORISEE, Status.ARCHIVEE}),
    Status.AUTORISEE: frozenset({Status.ACTIVE, Status.ARCHIVEE}),
    Status.ACTIVE: frozenset({Status.SUSPENDUE, Status.ARCHIVEE}),
    Status.SUSPENDUE: frozenset({Status.ACTIVE, Status.ARCHIVEE}),
    Status.ARCHIVEE: frozenset(),
}

# Champs modifiables hors cycle de vie ; le statut, lui, ne change que par transition.
EDITABLE_FIELDS = frozenset(
    {"name", "short_name", "type", "country_code", "timezone", "retention_days", "is_demo"}
)


MAX_REASON_LENGTH = 500  # le motif est conservé tel quel dans le journal d'audit (P2.7)


def _require_reason(reason: str) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ValueError("Un motif est obligatoire.")
    if len(cleaned) > MAX_REASON_LENGTH:
        raise ValueError(f"Le motif ne doit pas dépasser {MAX_REASON_LENGTH} caractères.")
    return cleaned


def _locked(organization: Organization) -> Organization:
    return Organization.objects.select_for_update().get(pk=organization.pk)


def _transition(
    scope: PlatformScope, organization: Organization, target: str, *, reason: str | None = None
) -> Organization:
    org = _locked(organization)
    if target not in TRANSITIONS[org.status]:
        record_event(
            "organization.transition",
            outcome="denied",
            actor_id=scope.actor_id,
            organization_id=org.pk,
            scope="platform",
            object_type="organization",
            object_id=org.pk,
            details={"from": org.status, "to": target, "demo": org.is_demo},
        )
        raise InvalidTransition(f"Transition {org.status} → {target} non autorisée.")
    previous = org.status
    org.status = target
    org.save(update_fields=["status", "updated_at"])
    record_event(
        "organization.transition",
        outcome="success",
        actor_id=scope.actor_id,
        organization_id=org.pk,
        scope="platform",
        object_type="organization",
        object_id=org.pk,
        old_value={"status": previous},
        new_value={"status": target},
        details={"reason": reason, "demo": org.is_demo},
    )
    organization.refresh_from_db()
    return org


def current_authorization(
    organization: Organization, on: datetime.date | None = None
) -> OrganizationAuthorization | None:
    """Autorisation en vigueur à la date donnée (par défaut aujourd'hui, UTC)."""
    day = on or dj_timezone.now().date()
    return (
        organization.authorizations.filter(valid_from__lte=day)
        .exclude(valid_until__lt=day)
        .order_by("-valid_from")
        .first()
    )


def _require_valid_authorization(scope: PlatformScope, organization: Organization, action: str) -> None:
    if current_authorization(organization) is None:
        record_event(
            f"organization.{action}",
            outcome="denied",
            actor_id=scope.actor_id,
            organization_id=organization.pk,
            scope="platform",
            object_type="organization",
            object_id=organization.pk,
            details={"reason": "no_valid_authorization", "demo": organization.is_demo},
        )
        raise InvalidTransition("Aucune autorisation formelle en vigueur pour cet organisme.")


# --- Demandes d'accès -----------------------------------------------------------------------


def submit_access_request(**data: Any) -> AccessRequest:
    """Enregistre une demande publique : aucun compte ni organisme n'est créé (écran 5)."""
    if data.get("consent") is not True:
        raise ValueError("Le consentement est obligatoire.")
    request = AccessRequest(**data, status=AccessRequest.Status.EN_ATTENTE)
    request.full_clean()
    request.save()
    record_event(
        "access_request.submit",
        outcome="success",
        actor_id=None,
        object_type="access_request",
        object_id=request.pk,
    )
    return request


@platform_operation()
@transaction.atomic
def reject_access_request(scope: PlatformScope, request: AccessRequest, *, reason: str) -> AccessRequest:
    require_scope(scope)
    reason = _require_reason(reason)
    locked = AccessRequest.objects.select_for_update().get(pk=request.pk)
    if locked.status != AccessRequest.Status.EN_ATTENTE:
        raise InvalidTransition("Demande déjà traitée.")
    locked.status = AccessRequest.Status.REJETEE
    locked.processed_at = dj_timezone.now()
    locked.processed_by_id = scope.actor_id
    locked.save(update_fields=["status", "processed_at", "processed_by", "updated_at"])
    record_event(
        "access_request.reject",
        outcome="success",
        actor_id=scope.actor_id,
        object_type="access_request",
        object_id=locked.pk,
        new_value={"status": locked.status},
        details={"reason": reason},
    )
    return locked


# --- Organismes ------------------------------------------------------------------------------


@platform_operation()
@transaction.atomic
def register_organization(
    scope: PlatformScope,
    *,
    name: str,
    short_name: str,
    type: str,
    country_code: str,
    timezone: str,
    retention_days: int,
    deployment_mode: str = Organization.DeploymentMode.MUTUALISE,
    is_demo: bool = False,
    access_request: AccessRequest | None = None,
) -> Organization:
    """Enregistre un organisme en EN_ATTENTE (demande enregistrée, aucun accès).

    Facultativement à partir d'une demande d'accès, qui passe alors en TRAITÉE.
    """
    require_scope(scope)
    organization = Organization(
        name=name.strip(),
        short_name=short_name.strip(),
        type=type,
        country_code=country_code,
        timezone=timezone,
        retention_days=retention_days,
        deployment_mode=deployment_mode,
        is_demo=is_demo,
        status=Status.EN_ATTENTE,
    )
    organization.full_clean()
    organization.save()
    if access_request is not None:
        locked = AccessRequest.objects.select_for_update().get(pk=access_request.pk)
        if locked.status != AccessRequest.Status.EN_ATTENTE:
            raise InvalidTransition("Demande déjà traitée.")
        locked.status = AccessRequest.Status.TRAITEE
        locked.organization = organization
        locked.processed_at = dj_timezone.now()
        locked.processed_by_id = scope.actor_id
        locked.save(update_fields=["status", "organization", "processed_at", "processed_by", "updated_at"])
    record_event(
        "organization.register",
        outcome="success",
        actor_id=scope.actor_id,
        organization_id=organization.pk,
        scope="platform",
        object_type="organization",
        object_id=organization.pk,
        new_value={"status": organization.status, "short_name": organization.short_name},
        details={
            "access_request": access_request.pk if access_request else None,
            "demo": organization.is_demo,
        },
    )
    return organization


@platform_operation()
@transaction.atomic
def update_organization(scope: PlatformScope, organization: Organization, **changes: Any) -> Organization:
    require_scope(scope)
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"Champs non modifiables par cette opération : {', '.join(sorted(unknown))}")
    org = _locked(organization)
    if org.status == Status.ARCHIVEE:
        raise InvalidTransition("Un organisme archivé n'est plus modifiable.")
    before = {field: getattr(org, field) for field in sorted(changes)}
    for field, value in changes.items():
        setattr(org, field, value.strip() if isinstance(value, str) else value)
    org.full_clean()
    org.save(update_fields=[*changes.keys(), "updated_at"])
    record_event(
        "organization.update",
        outcome="success",
        actor_id=scope.actor_id,
        organization_id=org.pk,
        scope="platform",
        object_type="organization",
        object_id=org.pk,
        old_value=before,
        new_value={field: getattr(org, field) for field in sorted(changes)},
        details={"fields": sorted(changes), "demo": org.is_demo},  # statut APRÈS la modification
    )
    organization.refresh_from_db()
    return org


@platform_operation()
@transaction.atomic
def authorize_organization(
    scope: PlatformScope,
    organization: Organization,
    *,
    reference: str,
    scope_text: str,
    valid_from: datetime.date,
    valid_until: datetime.date | None = None,
) -> OrganizationAuthorization:
    """Formalise l'autorisation (convention, période, périmètre) et passe l'organisme en AUTORISÉE."""
    require_scope(scope)
    org = _locked(organization)
    if Status.AUTORISEE not in TRANSITIONS[org.status]:
        raise InvalidTransition(f"Transition {org.status} → {Status.AUTORISEE} non autorisée.")
    authorization = OrganizationAuthorization(
        organization=org,
        reference=reference.strip(),
        scope=scope_text.strip(),
        valid_from=valid_from,
        valid_until=valid_until,
        granted_by_id=scope.actor_id,
    )
    authorization.full_clean()
    authorization.save()
    _transition(scope, org, Status.AUTORISEE)
    organization.refresh_from_db()
    return authorization


@platform_operation()
@transaction.atomic
def add_authorization(
    scope: PlatformScope,
    organization: Organization,
    *,
    reference: str,
    scope_text: str,
    valid_from: datetime.date,
    valid_until: datetime.date | None = None,
) -> OrganizationAuthorization:
    """Ajoute une autorisation (renouvellement, avenant) sans changer le statut."""
    require_scope(scope)
    org = _locked(organization)
    if org.status == Status.ARCHIVEE:
        raise InvalidTransition("Un organisme archivé n'est plus modifiable.")
    authorization = OrganizationAuthorization(
        organization=org,
        reference=reference.strip(),
        scope=scope_text.strip(),
        valid_from=valid_from,
        valid_until=valid_until,
        granted_by_id=scope.actor_id,
    )
    authorization.full_clean()
    authorization.save()
    record_event(
        "organization.authorization.add",
        outcome="success",
        actor_id=scope.actor_id,
        organization_id=org.pk,
        scope="platform",
        object_type="organization_authorization",
        object_id=authorization.pk,
        new_value={
            "reference": authorization.reference,
            "valid_from": authorization.valid_from,
            "valid_until": authorization.valid_until,
        },
        details={"demo": org.is_demo},
    )
    return authorization


@platform_operation()
@transaction.atomic
def activate_organization(scope: PlatformScope, organization: Organization) -> Organization:
    """AUTORISÉE → ACTIVE, sous réserve d'une autorisation en vigueur.

    Exige aussi un Administrateur institutionnel actif (§9.16, étape 5). La déclaration des sources de données
    (étape 6) deviendra une précondition avec le module d'ingestion.
    """
    require_scope(scope)
    org = _locked(organization)
    if org.status != Status.AUTORISEE:
        raise InvalidTransition(f"Activation impossible depuis le statut {org.status}.")
    _require_valid_authorization(scope, org, "activate")
    from apps.users.services import has_active_institutional_admin

    if not has_active_institutional_admin(scope, org.pk):
        record_event(
            "organization.activate",
            outcome="denied",
            actor_id=scope.actor_id,
            organization_id=org.pk,
            scope="platform",
            object_type="organization",
            object_id=org.pk,
            details={"reason": "no_institutional_admin", "demo": org.is_demo},
        )
        raise InvalidTransition("Aucun Administrateur institutionnel actif : activation impossible.")
    return _transition(scope, organization, Status.ACTIVE)


@platform_operation()
@transaction.atomic
def suspend_organization(scope: PlatformScope, organization: Organization, *, reason: str) -> Organization:
    """ACTIVE → SUSPENDUE : connexions bloquées, données conservées, aucune ingestion."""
    require_scope(scope)
    return _transition(scope, organization, Status.SUSPENDUE, reason=_require_reason(reason))


@platform_operation()
@transaction.atomic
def reactivate_organization(scope: PlatformScope, organization: Organization, *, reason: str) -> Organization:
    require_scope(scope)
    reason = _require_reason(reason)
    org = _locked(organization)
    if org.status != Status.SUSPENDUE:
        raise InvalidTransition(f"Réactivation impossible depuis le statut {org.status}.")
    _require_valid_authorization(scope, org, "reactivate")
    return _transition(scope, organization, Status.ACTIVE, reason=reason)


@platform_operation()
@transaction.atomic
def archive_organization(scope: PlatformScope, organization: Organization, *, reason: str) -> Organization:
    """Fin d'autorisation (ou rejet d'une demande enregistrée) : statut définitif, données conservées."""
    require_scope(scope)
    return _transition(scope, organization, Status.ARCHIVEE, reason=_require_reason(reason))
