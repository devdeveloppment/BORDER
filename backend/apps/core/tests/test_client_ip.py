"""P2.10 — Politique unique de l'adresse cliente et du proxy de confiance (ADR 0012).

Tests positifs et négatifs : en-tête forgé ignoré hors proxy déclaré, adresse propagée par le proxy déclaré,
limitation de débit et journal d'audit sur la même adresse, configuration douteuse refusée. Le comportement de
la pile réelle derrière Nginx est vérifié par ``tests/foundation/test_nginx_proxy.py``.
"""

from __future__ import annotations

import ipaddress
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle

from apps.audit.models import AuditLog
from apps.core import client_ip as policy
from apps.core.api import throttling as rbi_throttling
from apps.core.tests.api_support import ApiClient, iter_routes
from conftest import owner

PROXY = "172.29.89.2"
TRUSTED = (ipaddress.ip_network(f"{PROXY}/32"),)


@pytest.fixture
def trusted_proxy() -> Any:
    """Déclare le proxy le temps du test (le cache de la configuration validée est vidé avant et après)."""
    policy.trusted_networks.cache_clear()
    with override_settings(RBI_TRUSTED_PROXIES=[f"{PROXY}/32"]):
        yield
    policy.trusted_networks.cache_clear()


# --- Fonction pure ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("remote", "forwarded", "expected"),
    [
        ("198.51.100.7", "203.0.113.9", "198.51.100.7"),  # pair non déclaré : en-tête ignoré
        ("198.51.100.7", None, "198.51.100.7"),
        ("2001:db8::7", "203.0.113.9", "2001:db8::7"),
        (PROXY, "203.0.113.9", "203.0.113.9"),  # proxy déclaré : adresse transmise
        (PROXY, "10.0.0.1, 203.0.113.9", "203.0.113.9"),  # entrée la plus à droite
        (PROXY, f"203.0.113.9, {PROXY}", "203.0.113.9"),  # proxys déclarés sautés
        (PROXY, "198.51.100.1, pas-une-ip, 203.0.113.9", "203.0.113.9"),
        (PROXY, "203.0.113.9, pas-une-ip", PROXY),  # valeur invérifiable : adresse du proxy
        (PROXY, "", PROXY),
        (PROXY, None, PROXY),
        ("pas-une-ip", "203.0.113.9", None),
        (None, None, None),
    ],
)
def test_resolution_policy(remote: Any, forwarded: Any, expected: str | None) -> None:
    assert policy.resolve_client_ip(remote, forwarded, TRUSTED) == expected


def test_without_declared_proxy_the_header_is_never_used() -> None:
    assert policy.resolve_client_ip(PROXY, "203.0.113.9", ()) == PROXY


@pytest.mark.parametrize(
    "entries",
    [["0.0.0.0/0"], ["::/0"], ["10.0.0.0/8"], ["2001:db8::/32"], ["pas-un-réseau"], ["172.29.89.1/24"], [""]],
)
def test_ambiguous_or_invalid_configuration_is_refused(entries: list[str]) -> None:
    with pytest.raises(ImproperlyConfigured):
        policy.parse_trusted_proxies(entries)


def test_narrow_configuration_is_accepted() -> None:
    assert policy.parse_trusted_proxies([f"{PROXY}/32", "172.29.89.0/28", "2001:db8::/64"]) == (
        ipaddress.ip_network(f"{PROXY}/32"),
        ipaddress.ip_network("172.29.89.0/28"),
        ipaddress.ip_network("2001:db8::/64"),
    )


def test_invalid_configuration_stops_the_application() -> None:
    policy.trusted_networks.cache_clear()
    try:
        with override_settings(RBI_TRUSTED_PROXIES=["0.0.0.0/0"]), pytest.raises(ImproperlyConfigured):
            from django.apps import apps

            apps.get_app_config("core").ready()
    finally:
        policy.trusted_networks.cache_clear()


# --- Requêtes réelles (middleware, audit, limitation) ------------------------------------------------------


def _anonymous_problem(client: Client, **meta: str) -> Any:
    extra: Any = meta  # le client de test accepte des en-têtes META arbitraires
    return client.post("/api/v1/auth/login", data="{}", content_type="application/json", **extra)


@pytest.mark.django_db
def test_forged_header_from_an_untrusted_peer_is_stripped_and_audited_with_the_peer(
    trusted_proxy: Any,
) -> None:
    api = ApiClient()
    api.post(
        "/auth/login",
        {"email": "x@demo.test", "password": "x"},
        REMOTE_ADDR="198.51.100.7",
        HTTP_X_FORWARDED_FOR="203.0.113.9",
        HTTP_X_FORWARDED_PROTO="https",
    )
    with owner():
        entry = AuditLog.objects.filter(action="auth.login").latest("id")
    assert entry.ip_address == "198.51.100.7"


@pytest.mark.django_db
def test_address_forwarded_by_the_declared_proxy_is_audited(trusted_proxy: Any) -> None:
    api = ApiClient()
    api.post(
        "/auth/login",
        {"email": "x@demo.test", "password": "x"},
        REMOTE_ADDR=PROXY,
        HTTP_X_FORWARDED_FOR="203.0.113.9",
    )
    with owner():
        entry = AuditLog.objects.filter(action="auth.login").latest("id")
    assert entry.ip_address == "203.0.113.9"


@pytest.mark.django_db
def test_forwarded_proto_is_only_believed_from_the_declared_proxy(trusted_proxy: Any) -> None:
    seen: dict[str, bool] = {}

    def view(request: Any) -> Any:
        from django.http import HttpResponse

        seen[request.META["REMOTE_ADDR"]] = request.is_secure()
        return HttpResponse()

    middleware = policy.TrustedProxyMiddleware(view)
    from django.test import RequestFactory

    factory = RequestFactory()
    with override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")):
        middleware(factory.get("/", REMOTE_ADDR="198.51.100.7", HTTP_X_FORWARDED_PROTO="https"))
        middleware(factory.get("/", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_PROTO="https"))
    assert seen == {"198.51.100.7": False, PROXY: True}


@pytest.mark.django_db
def test_rate_limit_applies_to_the_forwarded_client_not_to_the_proxy(
    trusted_proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        SimpleRateThrottle, "THROTTLE_RATES", {**SimpleRateThrottle.THROTTLE_RATES, "anon": "2/min"}
    )
    api = ApiClient()

    def get(client_address: str) -> int:
        return int(
            api.client.get(
                "/api/v1/auth/csrf", REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=client_address
            ).status_code
        )

    assert [get("203.0.113.1") for _ in range(3)] == [204, 204, 429]
    # Un autre client derrière le même proxy garde son propre quota : pas de compteur unique pour tous.
    assert get("203.0.113.2") == 204


@pytest.mark.django_db
def test_rate_limit_of_a_direct_client_ignores_a_forged_header(
    trusted_proxy: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        SimpleRateThrottle, "THROTTLE_RATES", {**SimpleRateThrottle.THROTTLE_RATES, "anon": "2/min"}
    )
    client = Client()
    statuses = [
        client.get(
            "/api/v1/auth/csrf", REMOTE_ADDR="198.51.100.7", HTTP_X_FORWARDED_FOR=f"203.0.113.{n}"
        ).status_code
        for n in range(3)
    ]
    assert statuses == [204, 204, 429]


@pytest.mark.django_db
def test_login_lockout_uses_the_forwarded_client(trusted_proxy: Any) -> None:
    from apps.authentication import throttling

    request = type("R", (), {"META": {"REMOTE_ADDR": PROXY, "HTTP_X_FORWARDED_FOR": "203.0.113.5"}})()
    assert throttling.client_ip(request) == "203.0.113.5"


def test_every_api_view_uses_the_rbi_throttle_classes() -> None:
    allowed = {
        rbi_throttling.AnonRateThrottle,
        rbi_throttling.UserRateThrottle,
        rbi_throttling.ScopedRateThrottle,
    }
    for route, callback in iter_routes():
        view_class = getattr(callback, "cls", None)
        if view_class is None:
            continue
        for throttle in view_class().get_throttles():
            assert isinstance(throttle, BaseThrottle)
            assert type(throttle) in allowed, (
                f"{route} : {type(throttle).__module__}.{type(throttle).__name__}"
            )


def test_tenant_context_never_comes_from_a_header() -> None:
    """Rappel P2.3/P2.6 : aucun en-tête n'entre dans le contexte d'organisme (lecture du code)."""
    from pathlib import Path

    from django.conf import settings

    for name in ("apps/organizations/middleware.py", "apps/organizations/tenancy.py"):
        source = (Path(settings.BASE_DIR) / name).read_text(encoding="utf-8")
        assert "META" not in source and "headers" not in source
