from __future__ import annotations

import pytest
from django.test import Client

from apps.health import services

pytestmark = pytest.mark.django_db


def test_live(client: Client) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "no-cache" in response["Cache-Control"]


def test_ready(client: Client) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "cache": "ok"}}


def test_ready_reports_failure_without_leaking_details(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise ConnectionError("redis://:motdepasse-fictif@redis:6379/2 injoignable")

    monkeypatch.setitem(services.CHECKS, "cache", broken)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "ok", "cache": "error"}}
    assert b"motdepasse" not in response.content


def test_health_is_read_only(client: Client) -> None:
    assert client.post("/api/v1/health/live").status_code == 405
