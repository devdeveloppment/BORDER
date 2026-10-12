"""Garde-fou de démarrage : refuse un rôle PostgreSQL capable de contourner le Row-Level Security.

Exécuté avant l'API et le worker (docker-compose.yml). Un superutilisateur, un rôle BYPASSRLS
ou le propriétaire des tables ne sont pas soumis aux politiques RLS (sauf FORCE) :
l'application ne doit jamais tourner avec eux.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Vérifie que la connexion applicative utilise un rôle non privilégié, soumis au RLS."

    def handle(self, *args: Any, **options: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.rolname, r.rolsuper, r.rolbypassrls,
                       (SELECT count(*) FROM pg_class c
                         JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relowner = r.oid AND n.nspname = 'public' AND c.relkind IN ('r', 'p')),
                       (SELECT count(*) FROM pg_auth_members m WHERE m.member = r.oid)
                  FROM pg_roles r
                 WHERE r.rolname = current_user
                """
            )
            row = cursor.fetchone()
        if row is None:
            raise CommandError("Rôle PostgreSQL courant introuvable.")
        role, is_superuser, bypasses_rls, owned_tables, memberships = row

        problems = []
        if is_superuser:
            problems.append("superutilisateur")
        if bypasses_rls:
            problems.append("attribut BYPASSRLS")
        if owned_tables:
            problems.append(f"propriétaire de {owned_tables} table(s)")
        if memberships:
            problems.append(f"membre de {memberships} rôle(s)")
        if problems:
            raise CommandError(
                f"Rôle PostgreSQL « {role} » refusé pour l'application : {', '.join(problems)}. "
                "Utiliser le rôle applicatif (RBI_DB_APP_USER)."
            )
        self.stdout.write(f"Rôle PostgreSQL « {role} » conforme : non privilégié, soumis au RLS.")
