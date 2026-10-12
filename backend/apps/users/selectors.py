"""Lectures sur les utilisateurs : toujours limitées à l'organisme du contexte serveur."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import connection

from apps.core.db_scope import db_scope
from apps.organizations.tenancy import TenantContext

from .models import User, UserRole
from .rbac import PermissionDeniedError, has_permission, permission_codes, require_permission, role_codes


def list_organization_users(actor: User, context: TenantContext) -> list[User]:
    """Utilisateurs de l'organisme uniquement (écran 23). Lecture : ``users.view`` ou ``users.manage``."""
    if not has_permission(actor, "users.manage", context):
        require_permission(actor, "users.view", context)
    with db_scope(current_user=actor.pk, current_org=context.organization_id, auth_email="", platform=""):
        return list(User.objects.filter(organization_id=context.organization_id).order_by("email"))


def describe_access(user: User, context: TenantContext | None) -> dict[str, Any]:
    """Rôles et permissions effectifs (préfigure ``GET /api/v1/me``, P2.5/P2.8).

    Ne lève jamais : en cas de refus, listes vides.
    """
    if user.organization_id is not None and (
        context is None or context.organization_id != user.organization_id
    ):
        return {"roles": [], "permissions": []}
    return {"roles": sorted(role_codes(user)), "permissions": sorted(permission_codes(user))}


@dataclass(frozen=True, slots=True)
class OrganizationUserRow:
    """Compte de l'organisme tel que présenté par l'API (écran 23) : aucun secret, aucun hachage."""

    user: User
    roles: list[str]
    mfa_enabled: bool


def organization_user_rows(
    actor: User, context: TenantContext, user_id: uuid.UUID | None = None
) -> list[OrganizationUserRow]:
    """Comptes de l'organisme du CONTEXTE (``users.view``), avec rôles et statut MFA, lus dans un seul
    périmètre.

    ``user_id`` : un seul compte ; un compte d'un autre organisme est indiscernable d'un compte inexistant
    (``User.DoesNotExist`` → 404). Le statut MFA d'autrui passe par ``rbi_org_mfa_enabled_users()`` (P2.8) :
    les appareils et leurs secrets restent illisibles.
    """
    require_permission(actor, "users.view", context)
    org = context.organization_id
    with db_scope(current_user=actor.pk, current_org=org, auth_email="", platform=""):
        users = User.objects.filter(organization_id=org)
        if user_id is not None:
            users = users.filter(pk=user_id)
        accounts = list(users.order_by("email", "id"))
        if user_id is not None and not accounts:
            raise User.DoesNotExist
        roles: dict[uuid.UUID, list[str]] = {}
        for owner_id, code in (
            UserRole.objects.filter(
                organization_id=org,
                scope="organization",
                role__scope="organization",
                user_id__in=[u.pk for u in accounts],
            )
            .order_by("role__code")
            .values_list("user_id", "role__code")
        ):
            roles.setdefault(owner_id, []).append(code)
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM rbi_org_mfa_enabled_users()")
            enrolled = {row[0] for row in cursor.fetchall()}
    return [OrganizationUserRow(u, roles.get(u.pk, []), u.pk in enrolled) for u in accounts]


__all__ = [
    "OrganizationUserRow",
    "PermissionDeniedError",
    "describe_access",
    "list_organization_users",
    "organization_user_rows",
]
