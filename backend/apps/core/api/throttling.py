"""Classes de limitation de débit de l'API (P2.10) : l'identité d'un client anonyme est l'adresse de la
politique unique du proxy de confiance (``apps.core.client_ip``), jamais l'en-tête ``X-Forwarded-For`` lu par
DRF. Toute vue de l'API utilise ces classes (vérifié par ``apps/core/tests/test_client_ip.py``)."""

from __future__ import annotations

from typing import Any

from rest_framework import throttling

from apps.core.client_ip import client_ip


class ClientAddressMixin:
    def get_ident(self, request: Any) -> str:
        return client_ip(request) or "unknown"


class AnonRateThrottle(ClientAddressMixin, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(ClientAddressMixin, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(ClientAddressMixin, throttling.ScopedRateThrottle):
    pass
