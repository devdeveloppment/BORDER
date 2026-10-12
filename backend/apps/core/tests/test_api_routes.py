"""Politique d'accès de TOUTES les routes (P2.8, ADR 0010) : table attendue, refus par défaut, permissions.

Une route ajoutée sans politique, une politique modifiée, une permission différente de celle attendue, une vue
DRF hors de la base RBI ou une route privée devenue publique font échouer ces tests.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.core.api.views import RBIAPIView, RBIPolicyMixin, by_method
from apps.organizations.models import Organization
from apps.users.models import User
from conftest import create_user

from .api_support import ApiClient, api_path, iter_routes, methods_of, signed_in

pytestmark = pytest.mark.django_db

PUBLIC, AUTHENTICATED = "public", "authenticated"

# Table de référence : (gabarit de route) → {méthode : politique}. Toute évolution est volontaire et revue
# ici.
EXPECTED: dict[str, dict[str, str]] = {
    "api/v1/health/live": {"GET": PUBLIC},
    "api/v1/health/ready": {"GET": PUBLIC},
    "api/v1/auth/csrf": {"GET": PUBLIC},
    "api/v1/auth/login": {"POST": PUBLIC},
    "api/v1/auth/mfa/enroll": {"POST": PUBLIC},
    "api/v1/auth/mfa/verify": {"POST": PUBLIC},
    "api/v1/auth/logout": {"POST": PUBLIC},
    "api/v1/auth/password-reset": {"POST": PUBLIC},
    "api/v1/auth/password-reset/confirm": {"POST": PUBLIC},
    "api/v1/auth/password/change": {"POST": AUTHENTICATED},
    "api/v1/auth/sessions/revoke-others": {"POST": AUTHENTICATED},
    "api/v1/auth/mfa/totp/renew": {"POST": AUTHENTICATED},
    "api/v1/auth/mfa/totp/renew/confirm": {"POST": AUTHENTICATED},
    "api/v1/auth/mfa/backup-codes": {"POST": AUTHENTICATED},
    "api/v1/auth/mfa/disable": {"POST": AUTHENTICATED},
    "api/v1/me": {"GET": AUTHENTICATED},
    "api/v1/schema": {"GET": AUTHENTICATED},
    "api/v1/public/access-requests": {"POST": PUBLIC},
    "api/v1/organization": {"GET": "organization.view"},
    "api/v1/users": {"GET": "users.view", "POST": "users.manage"},
    "api/v1/users/<uuid:user_id>": {"GET": "users.view", "PATCH": "users.manage"},
    "api/v1/users/<uuid:user_id>/roles": {"POST": "users.manage"},
    "api/v1/users/<uuid:user_id>/roles/<str:role>": {"DELETE": "users.manage"},
    "api/v1/users/<uuid:user_id>/mfa-reset": {"POST": "users.manage"},
    "api/v1/roles": {"GET": "users.view"},
    "api/v1/audit-logs": {"GET": "audit.view"},
    "api/v1/audit-logs/export": {"GET": "audit.view"},
    "api/v1/audit-logs/integrity": {"GET": "audit.view"},
    "api/v1/platform/organizations": {"GET": "platform.organizations", "POST": "platform.organizations"},
    "api/v1/platform/organizations/<uuid:organization_id>": {
        "GET": "platform.organizations",
        "PATCH": "platform.organizations",
    },
    "api/v1/platform/organizations/<uuid:organization_id>/status": {"POST": "platform.organizations"},
    "api/v1/platform/organizations/<uuid:organization_id>/authorizations": {"POST": "platform.organizations"},
    "api/v1/platform/organizations/<uuid:organization_id>/institutional-admins": {
        "POST": "platform.institutional_admins"
    },
    "api/v1/platform/access-requests/<uuid:request_id>/reject": {"POST": "platform.organizations"},
    "api/v1/platform/audit-logs": {"GET": "platform.audit"},
    "api/v1/platform/audit-logs/export": {"GET": "platform.audit"},
    "api/v1/platform/audit-logs/integrity": {"GET": "platform.audit"},
}
PLAIN_DJANGO_PUBLIC = {"api/v1/health/live", "api/v1/health/ready"}  # sondes de l'orchestrateur (P2.2)


def actual_policies() -> dict[str, dict[str, str]]:
    table: dict[str, dict[str, str]] = {}
    for route, view in iter_routes():
        cls = getattr(view, "cls", None)
        if cls is None:  # vue Django simple
            table[route] = {"GET": PUBLIC if getattr(view, "rbi_public", False) else "?"}
            continue
        policies = {}
        for method in methods_of(view):
            policy = cls.policy(method) if issubclass(cls, RBIPolicyMixin) else "?"
            policies[method] = policy.removeprefix("permission:")
        table[route] = policies
    return table


def test_every_route_has_the_expected_policy() -> None:
    assert actual_policies() == EXPECTED


def test_every_api_view_uses_the_rbi_policy() -> None:
    for route, view in iter_routes():
        cls = getattr(view, "cls", None)
        if cls is None:
            assert route in PLAIN_DJANGO_PUBLIC and view.rbi_public, route
            continue
        assert issubclass(cls, RBIPolicyMixin), route
        assert view.csrf_exempt is False, route  # le middleware CSRF s'applique (ADR 0007)
        assert view.rbi_public is (EXPECTED[route] == dict.fromkeys(EXPECTED[route], PUBLIC)), route


def test_public_routes_are_exactly_the_expected_ones() -> None:
    public = {route for route, view in iter_routes() if getattr(view, "rbi_public", False)}
    assert public == {route for route, policies in EXPECTED.items() if set(policies.values()) == {PUBLIC}}
    assert len(public) == 10


def test_anonymous_is_refused_on_every_private_route_and_method() -> None:
    api = ApiClient()
    for route, view in iter_routes():
        if getattr(view, "rbi_public", False):
            continue
        for method in ("GET", "POST", "PATCH", "PUT", "DELETE"):
            response = api.request(
                method, api_path(route), {} if method in ("POST", "PATCH", "PUT") else None
            )
            assert response.status_code == 401, (method, route)
            assert response.json()["title"] == "Authentification requise"


@pytest.fixture
def powerless(org_a: Organization) -> dict[str, User]:
    """Comptes authentifiés sans aucune permission, dans chaque portée."""
    return {
        "organization": create_user("sans.role@demo-a.rbi.test", org_a),
        "platform": create_user("sans.role@plateforme.rbi.test"),
    }


def _permission_cases() -> list[tuple[str, str, str]]:
    return [
        (route, method, policy)
        for route, policies in EXPECTED.items()
        for method, policy in policies.items()
        if policy not in (PUBLIC, AUTHENTICATED)
    ]


@pytest.mark.parametrize(("route", "method", "permission"), _permission_cases())
def test_authenticated_without_the_permission_is_refused(
    route: str, method: str, permission: str, powerless: dict[str, User], admin_a: User, platform_admin: User
) -> None:
    """Un compte authentifié n'est pas autorisé pour autant : chaque route exige SA permission. Le compte de
    l'autre portée (Super Administrateur sur une route d'organisme, administrateur d'organisme sur une route
    plateforme) est refusé lui aussi."""
    scope = "platform" if permission.startswith("platform.") else "organization"
    other = admin_a if scope == "platform" else platform_admin
    for user in (powerless[scope], other):
        response = signed_in(user).request(
            method, api_path(route), {} if method in ("POST", "PATCH") else None
        )
        assert response.status_code == 403, (user.email, method, route, response.content)
        assert response.json() == {
            "type": "about:blank",
            "title": "Vous n'avez pas accès à cette ressource",
            "status": 403,
        }


@pytest.mark.parametrize("route", sorted(r for r, p in EXPECTED.items() if r not in PLAIN_DJANGO_PUBLIC))
def test_unsupported_methods_are_refused(route: str, admin_a: User, platform_admin: User) -> None:
    user = platform_admin if "/platform/" in route else admin_a
    api = signed_in(user)
    for method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} - set(EXPECTED[route]):
        response = api.request(method, api_path(route), {} if method in ("POST", "PATCH", "PUT") else None)
        assert response.status_code in (403, 405), (method, route)  # 405, ou 403 si la permission manque


def test_a_view_without_policy_cannot_be_defined() -> None:
    with pytest.raises(ImproperlyConfigured, match="exactement une politique"):

        class NoPolicy(RBIAPIView):
            def get(self, request: Any) -> Response:
                return Response({})

    with pytest.raises(ImproperlyConfigured, match="méthodes"):

        class PartialTable(RBIAPIView):
            permission = by_method(GET="users.view")

            def get(self, request: Any) -> Response:
                return Response({})

            def post(self, request: Any) -> Response:
                return Response({})

    with pytest.raises(ImproperlyConfigured, match="inconnue"):

        class UnknownPermission(RBIAPIView):
            permission = "users.everything"

            def get(self, request: Any) -> Response:
                return Response({})


def test_plain_drf_view_is_denied_by_default(admin_a: User) -> None:
    """Une vue DRF qui n'hériterait pas de la base RBI reçoit la permission par défaut : refus."""

    class Forgotten(APIView):
        def get(self, request: Any) -> Response:
            return Response({"secret": "fuite"})

    request = APIRequestFactory().get("/api/v1/forgotten")
    force_authenticate(request, user=admin_a)
    response = Forgotten.as_view()(request)
    assert response.status_code == 403


def test_super_admin_creation_is_not_exposed_over_http() -> None:
    """P2.5 : aucune route ne crée de compte plateforme ; la création d'un compte par HTTP n'attribue que des
    rôles d'organisme (vérifié dans apps/users/tests/test_users_api.py)."""
    routes = [route for route, _ in iter_routes()]
    assert routes and not any("super" in route for route in routes)
    assert not any(route.startswith("api/v1/platform/users") for route in routes)
