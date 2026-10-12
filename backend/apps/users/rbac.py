"""Évaluation des permissions côté serveur — refus par défaut.

Règles :
1. Code inconnu du catalogue : refusé.
2. Compte inactif ou non authentifié : refusé.
3. Permission ``platform`` : uniquement pour un compte plateforme (sans organisme),
   hors de tout contexte d'organisme.
4. Permission ``organization`` : uniquement pour un utilisateur organisationnel, avec un ``TenantContext``
   déterminé côté serveur et égal à l'organisme de l'utilisateur.
   **Un rôle n'est jamais une preuve d'appartenance** :
   l'appartenance vient de ``user.organization`` et du contexte, la permission vient du rôle.
5. Seules comptent les affectations cohérentes (portée du rôle = type de compte ; organisme de l'affectation =
   organisme de l'utilisateur) : une ligne incohérente insérée en contournant les services est ignorée.

Chaque refus de ``require_permission`` est audité.

P2.6 : les lectures RBAC d'un compte s'exécutent dans le périmètre PostgreSQL de CE compte
(``identity_scope``).
Sans cela, des lignes masquées par le RLS feraient conclure « aucun rôle » ou « pas de MFA » : un échec
permissif
pour ``requires_mfa``. Le périmètre est restauré à la sortie.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied

from apps.audit.services import record_event
from apps.core.db_scope import identity_scope
from apps.organizations.tenancy import TenantContext

from .catalog import PERMISSIONS_BY_CODE


class PermissionDeniedError(PermissionDenied):
    """Action non autorisée. Message générique : ne révèle ni la permission manquante ni la ressource."""


def _is_usable_account(user: Any) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False) and user.is_active)


def permission_codes(user: Any) -> frozenset[str]:
    """Permissions effectives de l'utilisateur, à sa propre portée uniquement."""
    if not _is_usable_account(user):
        return frozenset()
    from .models import Permission, UserRole

    if user.organization_id is None:
        assignments = UserRole.objects.filter(user=user, scope="platform", organization__isnull=True)
        scope = "platform"
    else:
        assignments = UserRole.objects.filter(
            user=user, scope="organization", organization_id=user.organization_id
        )
        scope = "organization"
    with identity_scope(user.pk):
        codes = (
            Permission.objects.filter(
                scope=scope,
                roles__scope=scope,
                roles__id__in=assignments.filter(role__scope=scope).values("role_id"),
            )
            .values_list("code", flat=True)
            .distinct()
        )
        return frozenset(codes)


def role_codes(user: Any) -> frozenset[str]:
    if not _is_usable_account(user):
        return frozenset()
    from .models import UserRole

    scope = "platform" if user.organization_id is None else "organization"
    rows = UserRole.objects.filter(user=user, scope=scope, role__scope=scope)
    if scope == "organization":
        rows = rows.filter(organization_id=user.organization_id)
    with identity_scope(user.pk):
        return frozenset(rows.values_list("role__code", flat=True))


def has_permission(user: Any, code: str, context: TenantContext | None = None) -> bool:
    definition = PERMISSIONS_BY_CODE.get(code)
    if definition is None or not _is_usable_account(user):
        return False
    if definition.scope == "platform":
        if user.organization_id is not None or context is not None:
            return False
    else:
        if user.organization_id is None or context is None:
            return False
        if not isinstance(context, TenantContext) or context.organization_id != user.organization_id:
            return False
    return code in permission_codes(user)


def require_permission(user: Any, code: str, context: TenantContext | None = None) -> None:
    if has_permission(user, code, context):
        return
    actor_id = getattr(user, "pk", None) if _is_usable_account(user) else None
    # Rattaché à l'organisme de l'ACTEUR (jamais à celui du contexte présenté, qui peut justement être la
    # cause du refus) : un refus n'écrit rien dans le journal d'un autre organisme.
    actor_org = getattr(user, "organization_id", None) if actor_id else None
    details: dict[str, object] = {"permission": code}
    if isinstance(context, TenantContext) and context.organization_id != actor_org:
        details["context_mismatch"] = True
    record_event(
        "rbac.check", outcome="denied", actor_id=actor_id, organization_id=actor_org, details=details
    )
    raise PermissionDeniedError("Vous n'avez pas accès à cette ressource.")


def requires_mfa(user: Any) -> bool:
    """MFA obligatoire si un rôle effectif l'exige (§9.12, §19.1). Appliqué à la connexion en P2.5."""
    if not _is_usable_account(user):
        return False
    from .models import UserRole

    scope = "platform" if user.organization_id is None else "organization"
    with identity_scope(user.pk):
        return UserRole.objects.filter(
            user=user, scope=scope, role__scope=scope, role__mfa_required=True
        ).exists()
