"""Utilitaires partagés des tests d'infrastructure."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"Variable d'environnement {name} absente : lancer via docker compose (profil tools).")
    return value


def connect(user_var: str, password_var: str, dbname: str | None = None) -> psycopg.Connection[Any]:
    """Connexion avec les identifiants désignés par les variables d'environnement données."""
    return psycopg.connect(
        host=env("RBI_DB_HOST"),
        port=int(env("RBI_DB_PORT")),
        dbname=dbname or env("RBI_DB_NAME"),
        user=env(user_var),
        password=env(password_var),
        connect_timeout=5,
    )
