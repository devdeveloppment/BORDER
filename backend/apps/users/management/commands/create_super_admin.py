"""Création d'un compte Super Administrateur (amorçage, accès serveur uniquement).

    docker compose run --rm migrate python manage.py create_super_admin --email admin@plateforme.example

Le mot de passe est demandé de façon masquée (ou lu sur l'entrée standard avec --password-stdin),
jamais passé en argument. La MFA sera exigée à la première connexion (P2.5).
"""

from __future__ import annotations

import getpass
import sys
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.users.models import User
from apps.users.services import bootstrap_super_admin


class Command(BaseCommand):
    help = "Crée un compte plateforme doté du rôle SUPER_ADMIN."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", required=True)
        parser.add_argument(
            "--password-stdin", action="store_true", help="Lire le mot de passe sur l'entrée standard."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if User.objects.filter(email=options["email"].strip().lower()).exists():
            raise CommandError("Un compte existe déjà avec cette adresse.")
        if options["password_stdin"]:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Mot de passe : ")
            if password != getpass.getpass("Confirmation : "):
                raise CommandError("Les mots de passe ne correspondent pas.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user = bootstrap_super_admin(email=options["email"], password=password)
        self.stdout.write(f"Super Administrateur créé : {user.email}")
