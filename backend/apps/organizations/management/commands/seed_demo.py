"""Données fictives de démonstration (P2.11, ADR 0013).

    docker compose run --rm --no-deps api python manage.py seed_demo --actor-email <super.admin@…>

Le compte acteur doit exister, être actif et détenir le rôle Super Administrateur : la commande ne crée, ne
promeut ni ne réinitialise jamais de compte. Refus explicite (sans écriture) si l'environnement n'est pas
« development » ou « test », si le rôle de base est le rôle propriétaire, ou si une donnée non marquée occupe
un sigle, un nom ou une adresse du jeu de démonstration. Relancer la commande ne crée aucun doublon.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.organizations.demo import SeedFailed, SeedRefused, seed_demo


class Command(BaseCommand):
    help = "Crée les données fictives de démonstration (deux organismes, cinq comptes par organisme)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--actor-email",
            required=True,
            help="Super Administrateur existant, actif, qui exécute les services.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            summary = seed_demo(options["actor_email"])
        except SeedRefused as exc:
            raise CommandError(str(exc)) from None
        except SeedFailed as exc:
            raise CommandError(str(exc)) from None
        for line in summary.lines():
            self.stdout.write(line)
