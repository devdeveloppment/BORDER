from __future__ import annotations

from celery import shared_task


@shared_task(name="health.ping")
def ping() -> str:
    """Tâche de vérification de la chaîne broker → worker → résultat (aucune donnée métier)."""
    return "pong"
