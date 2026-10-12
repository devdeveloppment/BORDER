"""Récupération MFA hors bande (accès serveur uniquement) : supprime les facteurs d'un compte et ferme ses
sessions.

    docker compose run --rm migrate python manage.py reset_user_mfa --email admin@plateforme.example

Destinée aux comptes plateforme (aucun administrateur au-dessus d'eux) ; pour un utilisateur d'organisme,
la réinitialisation passe par son Administrateur institutionnel. L'opération est auditée.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.authentication.services import server_reset_mfa
from apps.users.models import User


class Command(BaseCommand):
    help = "Réinitialise la MFA d'un compte (ré-enrôlement à la prochaine connexion)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            user = server_reset_mfa(options["email"])
        except User.DoesNotExist as exc:
            raise CommandError("Compte introuvable.") from exc
        self.stdout.write(f"MFA réinitialisée pour {user.email} ; toutes ses sessions sont fermées.")
