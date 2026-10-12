"""Outils des tests de l'API v1 (P2.8) : client HTTP avec CSRF réellement appliqué, routes énumérées.

``signed_in(user)`` ouvre une session dans l'état « connexion complète, MFA vérifiée » sans rejouer le
parcours mot de passe + TOTP : réservé aux matrices de permissions. Les parcours réels (mot de passe, MFA,
CSRF) sont testés de bout en bout (apps/authentication/tests, apps/audit/tests/test_audit_api.py). Aucun
mécanisme de production n'est contourné : session, CSRF, politique de session, RBAC et RLS s'appliquent
normalement.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver

from apps.authentication.services import AUTH_AT_KEY, BACKEND, MFA_VERIFIED_KEY
from apps.users.models import User
from conftest import owner

SAMPLE = {"uuid": str(uuid.UUID(int=1)), "str": "AGENT"}


class ApiClient:
    def __init__(self) -> None:
        self.client = Client(enforce_csrf_checks=True)

    def csrf(self) -> str:
        token = self.client.cookies.get("csrftoken")
        if token is None:
            assert self.client.get("/api/v1/auth/csrf").status_code == 204
            token = self.client.cookies["csrftoken"]
        return str(token.value)

    def request(self, method: str, path: str, data: Any = None, *, csrf: bool = True, **extra: Any) -> Any:
        headers = dict(extra.pop("headers", {}))
        if method.upper() not in ("GET", "HEAD") and csrf:
            headers["X-CSRFToken"] = self.csrf()
        kwargs: dict[str, Any] = {"headers": headers, **extra}
        if data is not None:
            kwargs["data"] = json.dumps(data)
            kwargs["content_type"] = "application/json"
        return getattr(self.client, method.lower())(f"/api/v1{path}", **kwargs)

    def get(self, path: str, **extra: Any) -> Any:
        return self.request("GET", path, **extra)

    def post(self, path: str, data: Any = None, **extra: Any) -> Any:
        return self.request("POST", path, data if data is not None else {}, **extra)

    def patch(self, path: str, data: Any = None, **extra: Any) -> Any:
        return self.request("PATCH", path, data if data is not None else {}, **extra)

    def delete(self, path: str, **extra: Any) -> Any:
        return self.request("DELETE", path, **extra)


def signed_in(user: User) -> ApiClient:
    api = ApiClient()
    with owner():  # login() enregistre last_login : préparation hors du rôle applicatif
        api.client.force_login(user, backend=BACKEND)
    session = api.client.session
    session[AUTH_AT_KEY] = time.time()
    session[MFA_VERIFIED_KEY] = True
    session.save()
    return api


def iter_routes(resolver: URLResolver | None = None, prefix: str = "") -> list[tuple[str, Any]]:
    """(gabarit de route, vue) pour toutes les routes, imbriquées comprises."""
    found: list[tuple[str, Any]] = []
    for pattern in (resolver or get_resolver()).url_patterns:
        if isinstance(pattern, URLResolver):
            found += iter_routes(pattern, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            found.append((prefix + str(pattern.pattern), pattern.callback))
    return found


def concrete(route: str, **values: str) -> str:
    """Chemin réel (« /api/v1/… ») d'un gabarit ; paramètres par défaut : ``SAMPLE``."""

    def replace(match: re.Match[str]) -> str:
        converter, name = match.group(1), match.group(2)
        return values.get(name, SAMPLE[converter])

    return "/" + re.sub(r"<(\w+):(\w+)>", replace, route)


def api_path(route: str, **values: str) -> str:
    return concrete(route, **values).removeprefix("/api/v1")


def methods_of(view: Any) -> set[str]:
    cls = getattr(view, "cls", None)
    if cls is None:
        return {"GET"}
    return {m.upper() for m in ("get", "post", "put", "patch", "delete") if callable(getattr(cls, m, None))}
