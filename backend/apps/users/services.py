"""Gestion des utilisateurs et des affectations de rôles (§9.12, écrans 23-24).

Règles (toutes vérifiées côté serveur, refus audités) :
- pas d'auto-inscription : tout compte est créé par un administrateur habilité ;
- un Administrateur institutionnel n'agit que dans SON organisme (contexte serveur, jamais un identifiant
  fourni par le client)
  et n'attribue que des rôles de portée organisme ;
- un utilisateur ne peut ni s'attribuer un rôle, ni se retirer, ni se désactiver lui-même ;
- le dernier Administrateur institutionnel actif d'un organisme ne peut être ni retiré ni désactivé ;
- le premier Administrateur institutionnel est désigné par le Super Administrateur (§9.16, étape 5).
Les comptes créés n'ont pas de mot de passe utilisable : l'invitation sécurisée et la MFA relèvent de P2.5.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from typing import Any

from django.db import connection, transaction

from apps.audit.services import record_event
from apps.core.db_scope import db_scope
from apps.organizations.exceptions import InvalidTransition
from apps.organizations.models import Organization
from apps.organizations.platform import PlatformScope, platform_operation, require_scope
from apps.organizations.tenancy import TenantContext

from .catalog import INSTITUTIONAL_ADMIN
from .models import Role, Scope, User, UserRole
from .rbac import PermissionDeniedError, require_permission

INSTITUTIONAL_ADMINS_PERMISSION = "platform.institutional_admins"


def organization_operation[F: Callable[..., Any]](func: F) -> F:
    """Action d'administration d'un organisme, exécutée dans le périmètre PostgreSQL de l'organisme du
    CONTEXTE (déterminé côté serveur) et de l'acteur. ``require_permission`` reste la première instruction
    du service."""

    @functools.wraps(func)
    def wrapper(actor: User, context: TenantContext, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(context, TenantContext):
            raise PermissionDeniedError("Vous n'avez pas accès à cette ressource.")
        with db_scope(current_user=actor.pk, current_org=context.organization_id, auth_email="", platform=""):
            return func(actor, context, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class SelfManagementError(PermissionDeniedError):
    """Action d'administration d'un utilisateur sur son propre compte."""


class LastAdministratorError(InvalidTransition):
    """Retrait ou désactivation du dernier Administrateur institutionnel actif."""


def _deny(
    action: str, actor: User, context: TenantContext | None, reason: str, target: object = None
) -> None:
    record_event(
        action,
        outcome="denied",
        actor_id=actor.pk,
        organization_id=context.organization_id if context else None,
        object_type="user" if target else None,
        object_id=target,
        details={"reason": reason},
    )


def _organization_role(code: str) -> Role:
    """Rôle par défaut de portée organisme. Un code de rôle plateforme n'est jamais trouvé ici."""
    try:
        return Role.objects.get(
            code=code, scope=Scope.ORGANIZATION, organization__isnull=True, is_system=True
        )
    except Role.DoesNotExist as exc:
        raise PermissionDeniedError("Vous n'avez pas accès à cette ressource.") from exc


def _organization_user(context: TenantContext, user_id: uuid.UUID) -> User:
    """Utilisateur de l'organisme du contexte ; celui d'un autre organisme est indiscernable d'un inconnu."""
    return User.objects.get(pk=user_id, organization_id=context.organization_id)


def _active_admin_count(organization_id: uuid.UUID) -> int:
    # Verrouille les affectations ET les comptes joints (jamais le catalogue des rôles, en lecture seule).
    # Sans le verrou des comptes, une transaction concurrente qui attendait relisait l'ancienne valeur de
    # is_active : deux administrateurs pouvaient se désactiver mutuellement.
    rows = (
        UserRole.objects.select_for_update(of=("self", "user"))
        .select_related("user")
        .filter(
            organization_id=organization_id, role__code=INSTITUTIONAL_ADMIN, role__scope=Scope.ORGANIZATION
        )
    )
    return sum(1 for row in rows if row.user.is_active)


def _attach(user: User, role: Role, assigned_by: User | None) -> UserRole:
    return UserRole.objects.create(
        user=user,
        role=role,
        scope=role.scope,
        organization_id=user.organization_id if role.scope == Scope.ORGANIZATION else None,
        assigned_by=assigned_by,
    )


def _require_demo_organization(is_demo: bool, organization: Organization) -> None:
    """Un compte de démonstration n'existe que dans un organisme de démonstration (§26)."""
    if is_demo and not organization.is_demo:
        raise InvalidTransition("Un compte de démonstration exige un organisme de démonstration.")


# --- Niveau plateforme -----------------------------------------------------------------------


@transaction.atomic
def bootstrap_super_admin(*, email: str, password: str) -> User:
    """Amorçage (commande ``create_super_admin``, accès serveur) : compte plateforme + rôle SUPER_ADMIN.
    Réservé au rôle de maintenance : refusé avec le rôle applicatif (P2.6)."""
    from apps.core.maintenance import require_maintenance_role

    require_maintenance_role()
    user = User.objects.create_user(email=email, password=password, organization=None)
    role = Role.objects.get(code="SUPER_ADMIN", scope=Scope.PLATFORM, organization__isnull=True)
    _attach(user, role, assigned_by=None)
    record_event(
        "user.bootstrap_super_admin",
        outcome="success",
        actor_id=None,
        system=True,
        object_type="user",
        object_id=user.pk,
        new_value={"roles": ["SUPER_ADMIN"]},
        details={"channel": "maintenance"},
    )
    return user


@platform_operation(INSTITUTIONAL_ADMINS_PERMISSION)
@transaction.atomic
def create_institutional_admin(
    scope: PlatformScope,
    organization: Organization,
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    is_demo: bool = False,
) -> User:
    """Désigne le premier Administrateur institutionnel d'un organisme AUTORISÉ ou ACTIF (§9.16, étape 5)."""
    require_scope(scope, INSTITUTIONAL_ADMINS_PERMISSION)
    org = Organization.objects.select_for_update().get(pk=organization.pk)
    if org.status not in {Organization.Status.AUTORISEE, Organization.Status.ACTIVE}:
        raise InvalidTransition(f"Désignation impossible pour un organisme au statut {org.status}.")
    _require_demo_organization(is_demo, org)
    user = User.objects.create_user(
        email=email, first_name=first_name, last_name=last_name, organization=org, is_demo=is_demo
    )
    admin = _organization_role(INSTITUTIONAL_ADMIN)
    _attach(user, admin, assigned_by=None)
    record_event(
        "user.create_institutional_admin",
        outcome="success",
        actor_id=scope.actor_id,
        organization_id=org.pk,
        scope="platform",
        object_type="user",
        object_id=user.pk,
        new_value={"roles": [INSTITUTIONAL_ADMIN]},
        details={"demo": org.is_demo},
    )
    return user


# --- Niveau organisme ------------------------------------------------------------------------


@organization_operation
@transaction.atomic
def create_organization_user(
    actor: User,
    context: TenantContext,
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    roles: tuple[str, ...] = (),
    is_demo: bool = False,
) -> User:
    """Crée un compte dans l'organisme du CONTEXTE (jamais dans un organisme fourni par l'appelant)."""
    require_permission(actor, "users.manage", context)
    resolved = [_organization_role(code) for code in roles]
    if is_demo:
        _require_demo_organization(is_demo, Organization.objects.get(pk=context.organization_id))
    user = User.objects.create_user(
        email=email,
        first_name=first_name,
        last_name=last_name,
        organization_id=context.organization_id,
        is_demo=is_demo,
    )
    for role in resolved:
        _attach(user, role, assigned_by=actor)
    record_event(
        "user.create",
        outcome="success",
        actor_id=actor.pk,
        organization_id=context.organization_id,
        object_type="user",
        object_id=user.pk,
        new_value={"roles": sorted(roles), "is_active": user.is_active},
    )
    return user


@organization_operation
@transaction.atomic
def assign_role(actor: User, context: TenantContext, user_id: uuid.UUID, role_code: str) -> UserRole:
    require_permission(actor, "users.manage", context)
    target = _organization_user(context, user_id)
    if target.pk == actor.pk:
        _deny("user.role.assign", actor, context, "self_assignment", target.pk)
        raise SelfManagementError("Vous n'avez pas accès à cette ressource.")
    role = _organization_role(role_code)
    assignment, created = UserRole.objects.get_or_create(
        user=target,
        role=role,
        defaults={"scope": role.scope, "organization_id": context.organization_id, "assigned_by": actor},
    )
    if created:
        record_event(
            "user.role.assign",
            outcome="success",
            actor_id=actor.pk,
            organization_id=context.organization_id,
            object_type="user",
            object_id=target.pk,
            new_value={"role": role_code},
        )
    return assignment


@organization_operation
@transaction.atomic
def revoke_role(actor: User, context: TenantContext, user_id: uuid.UUID, role_code: str) -> None:
    require_permission(actor, "users.manage", context)
    target = _organization_user(context, user_id)
    role = _organization_role(role_code)
    if (
        role.code == INSTITUTIONAL_ADMIN
        and target.is_active
        and UserRole.objects.filter(user=target, role=role).exists()
        and _active_admin_count(context.organization_id) <= 1
    ):
        _deny("user.role.revoke", actor, context, "last_institutional_admin", target.pk)
        raise LastAdministratorError("Impossible de retirer le dernier Administrateur institutionnel.")
    deleted, _ = UserRole.objects.filter(
        user=target, role=role, organization_id=context.organization_id
    ).delete()
    if deleted:
        record_event(
            "user.role.revoke",
            outcome="success",
            actor_id=actor.pk,
            organization_id=context.organization_id,
            object_type="user",
            object_id=target.pk,
            old_value={"role": role_code},
        )


@organization_operation
@transaction.atomic
def set_user_active(actor: User, context: TenantContext, user_id: uuid.UUID, *, active: bool) -> User:
    require_permission(actor, "users.manage", context)
    target = User.objects.select_for_update().get(pk=user_id, organization_id=context.organization_id)
    if target.pk == actor.pk:
        _deny("user.set_active", actor, context, "self_management", target.pk)
        raise SelfManagementError("Vous n'avez pas accès à cette ressource.")
    if (
        not active
        and target.is_active
        and UserRole.objects.filter(
            user=target, role__code=INSTITUTIONAL_ADMIN, role__scope=Scope.ORGANIZATION
        ).exists()
        and _active_admin_count(context.organization_id) <= 1
    ):
        _deny("user.set_active", actor, context, "last_institutional_admin", target.pk)
        raise LastAdministratorError("Impossible de désactiver le dernier Administrateur institutionnel.")
    was_active = target.is_active
    target.is_active = active
    target.rotate_security_stamp()  # ferme immédiatement toutes ses sessions
    target.save(update_fields=["is_active", "security_stamp"])
    record_event(
        "user.activate" if active else "user.deactivate",
        outcome="success",
        actor_id=actor.pk,
        organization_id=context.organization_id,
        object_type="user",
        object_id=target.pk,
        old_value={"is_active": was_active},
        new_value={"is_active": active},
    )
    return target


def has_active_institutional_admin(scope: PlatformScope, organization_id: uuid.UUID) -> bool:
    """Précondition d'activation (opération plateforme). Fonction SQL ``rbi_org_has_active_admin`` : le
    périmètre
    plateforme n'a pas besoin de lire les comptes de l'organisme pour obtenir cette seule réponse."""
    require_scope(scope)
    with connection.cursor() as cursor:
        cursor.execute("SELECT rbi_org_has_active_admin(%s)", [organization_id])
        row = cursor.fetchone()
    return bool(row and row[0])


__all__ = [
    "LastAdministratorError",
    "SelfManagementError",
    "assign_role",
    "bootstrap_super_admin",
    "create_institutional_admin",
    "create_organization_user",
    "has_active_institutional_admin",
    "revoke_role",
    "set_user_active",
]
