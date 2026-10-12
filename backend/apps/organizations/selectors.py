"""Lectures sur les organismes."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from django.db import connection
from django.utils import timezone

from .models import AccessRequest, Organization, OrganizationAuthorization
from .platform import PlatformScope, platform_operation, require_scope
from .tenancy import TenantContext, tenant_context


def get_own_organization(context: TenantContext) -> Organization:
    """L'organisme du contexte courant (lecture « le sien » de l'Administrateur institutionnel, §7.3)."""
    with tenant_context(context):
        return Organization.objects.get(pk=context.organization_id)


@platform_operation()
def list_organizations(scope: PlatformScope, *, status: str | None = None) -> list[Organization]:
    """Liste plateforme des organismes : identité et statut, aucune donnée opérationnelle (écran 31)."""
    require_scope(scope)
    queryset = Organization.objects.all()
    return list(queryset.filter(status=status) if status else queryset)


@platform_operation()
def pending_access_requests(scope: PlatformScope) -> list[AccessRequest]:
    require_scope(scope)
    return list(AccessRequest.objects.filter(status=AccessRequest.Status.EN_ATTENTE).order_by("created_at"))


# --- Lectures de l'API (P2.8) -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrganizationView:
    """Organisme tel que présenté par l'API (contrat P1 ``PlatformOrganization``)."""

    organization: Organization
    users_count: int
    current_authorization: OrganizationAuthorization | None
    authorizations: list[OrganizationAuthorization]


def _current(
    authorizations: list[OrganizationAuthorization], day: datetime.date
) -> OrganizationAuthorization | None:
    valid = [
        a for a in authorizations if a.valid_from <= day and (a.valid_until is None or a.valid_until >= day)
    ]
    return max(valid, key=lambda a: (a.valid_from, a.created_at), default=None)


def describe_own_organization(context: TenantContext) -> OrganizationView:
    """L'organisme du contexte (``organization.view``) : nombre de comptes et autorisation en vigueur."""
    from apps.users.models import User

    with tenant_context(context):
        organization = Organization.objects.get(pk=context.organization_id)
        authorizations = list(OrganizationAuthorization.objects.filter(organization_id=organization.pk))
        users_count = User.objects.filter(organization_id=organization.pk).count()
    return OrganizationView(
        organization, users_count, _current(authorizations, timezone.now().date()), authorizations
    )


@platform_operation()
def describe_organizations(
    scope: PlatformScope, organization_id: uuid.UUID | None = None
) -> list[OrganizationView]:
    """Registre plateforme (écran 31) : identité, statut, autorisations, NOMBRE de comptes (statistique
    agrégée, via ``rbi_platform_org_user_counts()``) ; aucune donnée opérationnelle ni aucun compte
    d'organisme."""
    require_scope(scope)
    organizations = Organization.objects.order_by("name")
    if organization_id is not None:
        organizations = organizations.filter(pk=organization_id)
    rows = list(organizations)
    if organization_id is not None and not rows:
        raise Organization.DoesNotExist
    by_org: dict[uuid.UUID, list[OrganizationAuthorization]] = {}
    for authorization in OrganizationAuthorization.objects.filter(organization_id__in=[o.pk for o in rows]):
        by_org.setdefault(authorization.organization_id, []).append(authorization)
    with connection.cursor() as cursor:
        cursor.execute("SELECT organization_id, users_count FROM rbi_platform_org_user_counts()")
        counts = {row[0]: int(row[1]) for row in cursor.fetchall()}
    today = timezone.now().date()
    return [
        OrganizationView(o, counts.get(o.pk, 0), _current(by_org.get(o.pk, []), today), by_org.get(o.pk, []))
        for o in rows
    ]


@platform_operation()
def get_organization(scope: PlatformScope, organization_id: uuid.UUID) -> Organization:
    require_scope(scope)
    return Organization.objects.get(pk=organization_id)


@platform_operation()
def get_pending_access_request(scope: PlatformScope, request_id: uuid.UUID) -> AccessRequest:
    require_scope(scope)
    return AccessRequest.objects.get(pk=request_id)


@platform_operation("platform.institutional_admins")
def get_organization_for_admin_designation(scope: PlatformScope, organization_id: uuid.UUID) -> Organization:
    """Lecture de l'organisme visé par la désignation du premier Administrateur institutionnel."""
    require_scope(scope, "platform.institutional_admins")
    return Organization.objects.get(pk=organization_id)
