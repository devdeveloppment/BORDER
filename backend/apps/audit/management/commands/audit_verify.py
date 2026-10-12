"""Vérification de TOUTES les chaînes d'audit (maintenance, accès serveur uniquement) :

    docker compose run --rm migrate python manage.py audit_verify

Lecture transversale (tous les organismes) : réservée au rôle de maintenance, refusée avec le rôle applicatif.
Chaque chaîne vérifiée est journalisée (``audit.verify``, action système). Affiche la tête de chaque chaîne
(identifiant, empreinte, longueur) : à copier hors de la base (ancrage externe) pour pouvoir détecter plus
tard une réécriture complète par un rôle privilégié. Code de sortie non nul si une chaîne est altérée.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.audit.integrity import chain_keys, verify_chain
from apps.audit.services import record_event
from apps.core.maintenance import require_maintenance_role


class Command(BaseCommand):
    help = "Vérifie l'intégrité de toutes les chaînes du journal d'audit et affiche leurs têtes."

    def handle(self, *args: Any, **options: Any) -> None:
        require_maintenance_role()
        broken = []
        for key in chain_keys():
            report = verify_chain(key)
            record_event(
                "audit.verify",
                outcome="success" if report.intact else "failure",
                actor_id=None,
                system=True,
                object_type="audit_chain",
                object_id=key,
                details={"checked": report.checked, "intact": report.intact, "channel": "maintenance"},
            )
            self.stdout.write(json.dumps(report.as_dict(), ensure_ascii=False))
            if not report.intact:
                broken.append(key)
        if broken:
            raise CommandError(f"Chaîne(s) d'audit altérée(s) : {', '.join(broken)}")
