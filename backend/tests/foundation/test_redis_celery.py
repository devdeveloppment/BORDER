"""Redis depuis Django (cache) et chaîne Celery réelle : broker → worker → résultat."""

from __future__ import annotations

import uuid

import pytest
from celery.result import EagerResult
from django.core.cache import cache

from apps.health.tasks import ping
from config.celery import app as celery_app


def test_django_cache_uses_redis() -> None:
    key = f"tests:{uuid.uuid4().hex}"
    cache.set(key, {"ok": True}, timeout=30)
    assert cache.get(key) == {"ok": True}
    cache.delete(key)
    assert cache.get(key) is None


def test_celery_broker_reachable() -> None:
    with celery_app.connection_for_write() as conn:
        conn.ensure_connection(max_retries=1)
        assert conn.connected


def test_celery_round_trip_through_real_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # Les réglages de test exécutent les tâches sur place : ce test exige la chaîne réelle. Clé de
    # l'espace de noms Django (affecter conf.task_always_eager resterait sans effet).
    monkeypatch.setitem(celery_app.conf, "CELERY_TASK_ALWAYS_EAGER", False)
    result = ping.delay()
    assert not isinstance(result, EagerResult)  # passé par le broker, pas exécuté sur place
    assert result.get(timeout=20) == "pong"


def test_celery_accepts_json_only() -> None:
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_serializer == "json"
