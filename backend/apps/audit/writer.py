"""Écriture des événements dans ``audit_auditlog`` (ADR 0009).

Deux modes (``RBI_AUDIT_WRITE_MODE``) :

- ``autonomous`` (défaut, obligatoire hors tests — contrôle système ``rbi.E001``) : connexion PostgreSQL
  DÉDIÉE, propre au processus et au thread, une transaction courte par événement. Un refus ou un échec reste
  enregistré même si la transaction métier est ensuite annulée, et le verrou de la tête de chaîne n'est tenu
  que le temps d'une insertion (jamais pendant une transaction métier : pas d'interblocage avec elle).
- ``inline`` (tests unitaires uniquement) : insertion dans la transaction en cours de la connexion Django. Les
  données préparées par un test ne sont pas validées, donc invisibles d'une autre connexion ; le mode autonome
  est vérifié par des tests transactionnels dédiés.

Dans les deux modes :
- l'insertion s'exécute avec le **rôle applicatif** (``SET ROLE``), y compris lorsqu'elle est déclenchée par
  une commande de maintenance connectée en propriétaire : mêmes privilèges et mêmes politiques RLS pour tous ;
- le périmètre serveur de l'événement (organisme, compte, opération plateforme) est réappliqué par
  ``set_config(…, true)`` le temps de l'insertion, puis effacé ;
- ``INSERT`` sans ``RETURNING`` : l'écrivain n'a pas besoin de relire le journal (lecture réservée aux
  auditeurs par le RLS).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from django.conf import settings
from django.db import connection, connections
from psycopg import sql

from apps.core.db_scope import db_scope

WriteMode = Literal["autonomous", "inline"]

COLUMNS = (
    "scope",
    "organization_id",
    "actor_type",
    "actor_id",
    "action",
    "outcome",
    "object_type",
    "object_id",
    "old_value",
    "new_value",
    "metadata",
    "ip_address",
    "request_id",
)
# Construite à partir de constantes uniquement ; toutes les valeurs passent en paramètres.
_PLACEHOLDERS = ", ".join("%s::jsonb" if c.endswith(("_value", "metadata")) else "%s" for c in COLUMNS)
INSERT_SQL = f"INSERT INTO audit_auditlog ({', '.join(COLUMNS)}) VALUES ({_PLACEHOLDERS})"  # noqa: S608
SCOPE_SQL = (
    "SELECT set_config('app.current_org', %s, true), set_config('app.current_user', %s, true), "
    "set_config('app.auth_email', '', true), set_config('app.platform', %s, true)"
)


class AuditWriteError(RuntimeError):
    """L'événement n'a pas pu être enregistré dans le journal d'audit."""


@dataclass(frozen=True, slots=True)
class PreparedEvent:
    scope: str
    organization_id: uuid.UUID | None
    actor_type: str
    actor_id: uuid.UUID | None
    action: str
    outcome: str
    object_type: str | None
    object_id: str | None
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    metadata: dict[str, Any]
    ip_address: str | None
    request_id: uuid.UUID | None
    context_org: str
    context_user: str
    context_platform: str

    def params(self) -> list[Any]:
        def json_or_none(value: dict[str, Any] | None) -> str | None:
            return None if value is None else json.dumps(value, ensure_ascii=False)

        return [
            self.scope,
            str(self.organization_id) if self.organization_id else None,
            self.actor_type,
            str(self.actor_id) if self.actor_id else None,
            self.action,
            self.outcome,
            self.object_type,
            self.object_id,
            json_or_none(self.old_value),
            json_or_none(self.new_value),
            json.dumps(self.metadata, ensure_ascii=False),
            self.ip_address,
            str(self.request_id) if self.request_id else None,
        ]


def mode() -> WriteMode:
    value = getattr(settings, "RBI_AUDIT_WRITE_MODE", "autonomous")
    return "inline" if value == "inline" else "autonomous"


def write(event: PreparedEvent) -> None:
    if mode() == "inline":
        _write_inline(event)
    else:
        _write_autonomous(event)


# --- Mode inline (tests unitaires) ------------------------------------------------------------------------


def _write_inline(event: PreparedEvent) -> None:
    app_role = settings.RBI_DB_APP_ROLE
    with (
        db_scope(
            current_org=event.context_org,
            current_user=event.context_user,
            auth_email="",
            platform=event.context_platform,
        ),
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_user")
        row = cursor.fetchone()
        previous_role = str(row[0]) if row else ""
        if previous_role != app_role:
            cursor.execute("SET ROLE %s" % connection.ops.quote_name(app_role))  # noqa: UP031
        # En cas d'échec, l'annulation du point de sauvegarde de db_scope annule aussi SET ROLE.
        cursor.execute(INSERT_SQL, event.params())
        if previous_role != app_role:
            cursor.execute("SET ROLE %s" % connection.ops.quote_name(previous_role))  # noqa: UP031


# --- Mode autonome -----------------------------------------------------------------------------------------

_local = threading.local()


def _connect() -> psycopg.Connection[Any]:
    # Paramètres de la connexion Django « default » (en test : la base de test), autocommit : chaque événement
    # est une transaction explicite.
    db = connections["default"].settings_dict
    options = db.get("OPTIONS") or {}
    conn = psycopg.connect(
        host=str(db["HOST"]),
        port=str(db["PORT"]),
        dbname=str(db["NAME"]),
        user=str(db["USER"]),
        password=str(db["PASSWORD"]),
        connect_timeout=int(options.get("connect_timeout", 5)),
        application_name=f"{options.get('application_name', 'rbi')}-audit",
        autocommit=True,
    )
    conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(settings.RBI_DB_APP_ROLE)))
    return conn


def _connection() -> psycopg.Connection[Any]:
    conn: psycopg.Connection[Any] | None = getattr(_local, "conn", None)
    # Après un fork (Celery prefork), la connexion héritée appartient au parent : ne pas la réutiliser.
    if conn is None or conn.closed or getattr(_local, "pid", None) != os.getpid():
        conn = _connect()
        _local.conn, _local.pid = conn, os.getpid()
    return conn


def close_connection() -> None:
    conn: psycopg.Connection[Any] | None = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "pid", None) == os.getpid():
        conn.close()
    _local.conn = None


def _write_autonomous(event: PreparedEvent) -> None:
    for attempt in (1, 2):  # une seule nouvelle tentative, après une connexion perdue
        conn = _connection()
        try:
            with conn.transaction():
                conn.execute(SCOPE_SQL, [event.context_org, event.context_user, event.context_platform])
                conn.execute(INSERT_SQL, event.params())
            return
        except psycopg.OperationalError:
            close_connection()
            if attempt == 2:
                raise
