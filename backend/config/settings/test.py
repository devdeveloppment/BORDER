"""Tests pytest : base PostgreSQL/PostGIS réelle (jamais SQLite), créée par le rôle propriétaire."""

from __future__ import annotations

from .base import *  # noqa: F403
from .base import DATABASES, INSTALLED_APPS

RBI_ENV = "test"
DEBUG = False
ALLOWED_HOSTS = ["testserver"]

# Application de test uniquement (modèle géographique de vérification) : jamais chargée hors tests.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.gisprobe"]

DATABASES["default"]["CONN_MAX_AGE"] = 0
DATABASES["default"]["TEST"] = {"NAME": "test_rbi"}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Journal d'audit écrit dans la transaction du test (données de test non validées, invisibles d'une autre
# connexion). Le mode autonome de production est vérifié par apps/audit/tests/test_autonomous_writer.py.
RBI_AUDIT_WRITE_MODE = "inline"

# Tâches Celery exécutées immédiatement, dans le processus du test : aucune tâche n'atteint le worker de
# développement (broker partagé). Le test d'infrastructure de la chaîne réelle s'en retire explicitement
# (tests/foundation/test_redis_celery.py).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
