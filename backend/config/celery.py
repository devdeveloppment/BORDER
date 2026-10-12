"""Application Celery RBI (broker et résultats : Redis).

Les tâches métier arrivent avec leurs modules. Règle pour P2.3 / P2.6 : toute tâche portant sur des données
d'un organisme reçoit explicitement son organization_id et pose le contexte tenant dans sa propre transaction.
"""

from __future__ import annotations

import os

from celery import Celery

# Par défaut, réglages sûrs (DEBUG désactivé) ; développement et tests nomment leur module.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

app = Celery("rbi")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
