"""Synchronisation de la base sur apps.users.catalog (exécutée après chaque ``migrate``).

Idempotente. Crée ou met à jour les permissions et les rôles par défaut, fixe exactement leur composition,
supprime les permissions retirées du catalogue. Ne touche ni aux affectations ni aux rôles personnalisés (V1).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from .catalog import PERMISSIONS, ROLES, validate_catalog


@transaction.atomic
def sync_rbac_catalog(using: str = "default") -> None:
    from .models import Permission, Role, RolePermission

    validate_catalog()
    permissions: dict[str, Permission] = {}
    for definition in PERMISSIONS:
        permission, _ = Permission.objects.using(using).update_or_create(
            code=definition.code,
            defaults={
                "module": definition.module,
                "scope": definition.scope,
                "description": definition.description,
            },
        )
        permissions[definition.code] = permission
    Permission.objects.using(using).exclude(code__in=permissions).delete()
    scope_by_pk = {permission.pk: permission.scope for permission in permissions.values()}

    for role_def in ROLES:
        role, _ = Role.objects.using(using).update_or_create(
            code=role_def.code,
            scope=role_def.scope,
            organization=None,
            defaults={"name": role_def.name, "is_system": True, "mfa_required": role_def.mfa_required},
        )
        wanted = {permissions[code].pk for code in role_def.permissions}
        RolePermission.objects.using(using).filter(role=role).exclude(permission_id__in=wanted).delete()
        existing = set(
            RolePermission.objects.using(using).filter(role=role).values_list("permission_id", flat=True)
        )
        RolePermission.objects.using(using).bulk_create(
            RolePermission(
                role=role, permission_id=pk, role_scope=role.scope, permission_scope=scope_by_pk[pk]
            )
            for pk in wanted - existing
        )


def on_post_migrate(sender: Any, using: str = "default", **kwargs: Any) -> None:
    from django.db import connections

    # Après un retour arrière qui a supprimé les tables RBAC, il n'y a rien à synchroniser.
    tables = set(connections[using].introspection.table_names())
    if {"users_permission", "users_role", "users_role_permission"} <= tables:
        sync_rbac_catalog(using=using)
