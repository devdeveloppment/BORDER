"""Opérations de maintenance réservées au rôle propriétaire (service ``migrate`` : accès serveur uniquement).

Le rôle propriétaire n'est pas soumis au RLS (ADR 0008) : ces opérations ne doivent jamais s'exécuter avec le
rôle applicatif. Elles le vérifient explicitement plutôt que de compter sur un refus implicite.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connection


class MaintenanceRoleRequired(PermissionDenied):
    pass


def current_database_role() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        row = cursor.fetchone()
    return str(row[0]) if row else ""


def require_maintenance_role() -> None:
    if current_database_role() == settings.RBI_DB_APP_ROLE:
        raise MaintenanceRoleRequired(
            "Opération de maintenance : à exécuter avec le service migrate (rôle propriétaire)."
        )
