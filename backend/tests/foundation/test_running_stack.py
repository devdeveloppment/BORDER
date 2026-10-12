"""Conteneurs `api` et `migrate` réels et garde-fou de rôle PostgreSQL au démarrage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from typing import Any

import psycopg

API = "http://api:8000"


def _get(path: str) -> tuple[int, Any]:
    with urllib.request.urlopen(f"{API}{path}", timeout=5) as response:  # noqa: S310 - service interne
        return response.status, json.load(response)


def _owner_connection() -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=os.environ["RBI_DB_HOST"],
        port=int(os.environ["RBI_DB_PORT"]),
        dbname=os.environ["RBI_DB_NAME"],  # base de développement, migrée par le service `migrate`
        user=os.environ["RBI_DB_OWNER"],
        password=os.environ["RBI_DB_OWNER_PASSWORD"],
        connect_timeout=5,
    )


def test_api_container_ready() -> None:
    status, body = _get("/api/v1/health/ready")
    assert status == 200
    assert body == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}


def _check_db_role(user_var: str, password_var: str) -> subprocess.CompletedProcess[str]:
    """Exécute le garde-fou de démarrage contre la base de développement avec le rôle indiqué."""
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.development",
        "RBI_DB_USER": os.environ[user_var],
        "RBI_DB_PASSWORD": os.environ[password_var],
    }
    return subprocess.run(
        [sys.executable, "manage.py", "check_db_role"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_startup_guard_accepts_application_role() -> None:
    result = _check_db_role("RBI_DB_APP_USER", "RBI_DB_APP_PASSWORD")
    assert result.returncode == 0, result.stderr
    assert "conforme" in result.stdout


def test_startup_guard_rejects_table_owner() -> None:
    result = _check_db_role("RBI_DB_OWNER", "RBI_DB_OWNER_PASSWORD")
    assert result.returncode != 0
    assert "propriétaire" in result.stderr
    assert os.environ["RBI_DB_OWNER_PASSWORD"] not in result.stderr


def test_development_database_migrated_by_owner() -> None:
    with _owner_connection() as conn:
        owners = conn.execute(
            "SELECT DISTINCT tableowner FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'spatial_ref_sys'"
        ).fetchall()
        migrated = conn.execute("SELECT count(*) FROM django_migrations WHERE app = 'users'").fetchone()
        probe = conn.execute("SELECT to_regclass('public.gisprobe_probesite')").fetchone()
    assert owners == [(os.environ["RBI_DB_OWNER"],)]
    assert migrated is not None and migrated[0] >= 1
    assert probe == (None,)  # l'application de test n'existe pas dans la base de développement
