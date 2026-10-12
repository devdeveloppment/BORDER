"""Fixtures des tests d'authentification."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.core.cache import caches

from .support import Api


@pytest.fixture(autouse=True)
def _isolated_throttling() -> Iterator[None]:
    """Compteurs de tentatives remis à zéro (Redis des tests, base 4 : distincte du développement)."""
    caches["default"].clear()
    yield
    caches["default"].clear()


@pytest.fixture
def api() -> Api:
    return Api()
