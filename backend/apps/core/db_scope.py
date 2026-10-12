"""Périmètre de base de données transmis à PostgreSQL pour le Row-Level Security (P2.6, ADR 0008).

Variables PostgreSQL toujours posées par ``set_config(nom, valeur, true)``, équivalent paramétré de
``SET LOCAL`` : leur portée est la TRANSACTION courante, jamais la connexion.

- ``app.current_org`` : organisme du contexte serveur validé (requête authentifiée, tâche Celery explicite) ;
- ``app.current_user`` : compte authentifié, ou compte précis en cours de vérification (session, jeton) ;
- ``app.auth_email`` : recherche d'UN compte par e-mail (connexion, demande de réinitialisation) ;
- ``app.platform`` : permission d'un ``PlatformScope`` délivré (opération globale auditée).

Règles :
- ``db_scope`` ouvre ``transaction.atomic()`` (transaction ou point de sauvegarde) : hors transaction,
  ``SET LOCAL`` n'aurait aucun effet sous l'autocommit de Django ;
- un périmètre imbriqué hérite des valeurs non précisées et restaure exactement les précédentes en sortie ;
  en cas d'exception, l'annulation du point de sauvegarde restaure les valeurs côté PostgreSQL ;
- valeurs passées en paramètres SQL (jamais interpolées) ; identifiants validés comme UUID ;
- aucune valeur par défaut : sans périmètre, les politiques RLS ne laissent rien passer.

Ces variables protègent contre les oublis de filtre et les chemins de code sans contexte. Elles ne protègent
pas contre l'exécution de SQL arbitraire par un attaquant, qui pourrait les définir : ADR 0008, « Limites ».
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar

from django.db import connection, transaction

KEYS = ("current_org", "current_user", "auth_email", "platform")
_EMPTY: dict[str, str] = dict.fromkeys(KEYS, "")
_scope: ContextVar[dict[str, str]] = ContextVar("rbi_db_scope", default=_EMPTY)

_SET_SQL = "SELECT " + ", ".join(f"set_config('app.{key}', %s, true)" for key in KEYS)


def _normalize(key: str, value: object) -> str:
    if value is None or value == "":
        return ""
    if key in ("current_org", "current_user"):
        return str(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
    if key == "auth_email":
        return str(value).strip().lower()
    return str(value)


def _apply(values: dict[str, str]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(_SET_SQL, [values[key] for key in KEYS])


@contextmanager
def db_scope(**values: object) -> Iterator[dict[str, str]]:
    """Ouvre un périmètre transactionnel. Clés autorisées : ``KEYS`` ; valeur vide ou None = effacer."""
    unknown = set(values) - set(KEYS)
    if unknown:
        raise ValueError(f"Clés de périmètre inconnues : {sorted(unknown)}")
    previous = _scope.get()
    current = {**previous, **{key: _normalize(key, value) for key, value in values.items()}}
    token = _scope.set(current)
    try:
        with transaction.atomic():
            _apply(current)
            yield current
            _apply(previous)  # sortie normale d'un point de sauvegarde : rien ne doit survivre
    finally:
        _scope.reset(token)


def identity_scope(user_id: object) -> AbstractContextManager[dict[str, str]]:
    """Lecture/écriture des données d'UN compte (le sien) : aucun organisme, aucune recherche, aucune
    plateforme."""
    return db_scope(current_user=user_id, current_org="", auth_email="", platform="")


def current_scope() -> dict[str, str]:
    """Périmètre courant tel que suivi côté Python (introspection, tests)."""
    return dict(_scope.get())


def database_scope() -> dict[str, str]:
    """Valeurs effectivement visibles par PostgreSQL dans la transaction courante (vérifications, tests)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT " + ", ".join(f"current_setting('app.{key}', true)" for key in KEYS))
        row = cursor.fetchone()
    return {key: (value or "") for key, value in zip(KEYS, row or [], strict=False)}
