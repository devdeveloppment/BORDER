"""Contrôles de disponibilité des dépendances (sonde « ready », §23)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.core.cache import cache
from django.db import connection

logger = logging.getLogger(__name__)


def check_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def check_cache() -> None:
    cache.set("health:ready", "ok", timeout=10)
    if cache.get("health:ready") != "ok":
        raise RuntimeError("lecture du cache incohérente")


CHECKS: dict[str, Callable[[], None]] = {"database": check_database, "cache": check_cache}


def run_readiness_checks() -> dict[str, bool]:
    """Exécute chaque contrôle ; le détail de l'erreur est journalisé, jamais renvoyé au client."""
    results: dict[str, bool] = {}
    for name, check in CHECKS.items():
        try:
            check()
        except Exception:
            logger.exception("Contrôle de disponibilité en échec : %s", name)
            results[name] = False
        else:
            results[name] = True
    return results
