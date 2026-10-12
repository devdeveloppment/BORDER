"""Tests d'infrastructure (P2.1) : exécutés contre les services Docker Compose réels.

docker compose --profile tools run --rm backend pytest -m infra
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from .support import connect


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.nodeid.replace("\\", "/").startswith("tests/infra/"):
            item.add_marker(pytest.mark.infra)


@pytest.fixture
def owner_conn() -> Iterator[psycopg.Connection[Any]]:
    with connect("RBI_DB_OWNER", "RBI_DB_OWNER_PASSWORD") as conn:
        yield conn


@pytest.fixture
def app_conn() -> Iterator[psycopg.Connection[Any]]:
    with connect("RBI_DB_APP_USER", "RBI_DB_APP_PASSWORD") as conn:
        yield conn
