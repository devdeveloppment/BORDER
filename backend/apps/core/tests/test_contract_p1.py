"""Contrat du frontend P1 (``frontend/src/lib/api/types.ts``, ``endpoints.ts``) face à l'API réelle (P2.8).

- Routes livrées : la forme des réponses couvre les champs des types P1 (vérifiée ici et dans les tests de
  chaque module : ``OrgUser``, ``PlatformOrganization``, ``AccessRequest``, ``AuditPage``, ``AuditEntry``).
- Routes du contrat P1 sans modèle métier (phases suivantes) : NON exposées. Elles répondent 404 au format
  RFC 9457 — jamais de données simulées présentées comme réelles. Le frontend P1 les sert toujours par MSW.
"""

from __future__ import annotations

import pytest

from apps.organizations.models import Organization
from apps.users.models import User

from .api_support import ApiClient, signed_in

pytestmark = pytest.mark.django_db

P1_CURRENT_USER = {
    "id",
    "email",
    "first_name",
    "last_name",
    "roles",
    "permissions",
    "organization",
    "mfa_enabled",
    "mfa_required",
    "assigned_post_ids",
    "last_login",
}
P1_ORGANIZATION_SUMMARY = {
    "id",
    "name",
    "short_name",
    "type",
    "status",
    "country_code",
    "timezone",
    "deployment_mode",
    "is_demo",
}

# Contrat P1 sans fonctionnalité métier à ce stade : rapport P2.8, « Routes reportées ».
DEFERRED = [
    ("GET", "/dashboard"),
    ("GET", "/border-posts"),
    ("GET", "/border-posts/00000000-0000-0000-0000-000000000001"),
    ("GET", "/activities"),
    ("GET", "/activities/00000000-0000-0000-0000-000000000001"),
    ("GET", "/alerts"),
    ("GET", "/alerts/00000000-0000-0000-0000-000000000001"),
    ("POST", "/alerts/00000000-0000-0000-0000-000000000001/actions"),
    ("GET", "/analytics/compare"),
    ("GET", "/reports"),
    ("POST", "/reports"),
    ("GET", "/notifications"),
    ("POST", "/notifications/00000000-0000-0000-0000-000000000001/read"),
    ("POST", "/notifications/read-all"),
    ("GET", "/settings"),
    ("PATCH", "/settings"),
]


def test_me_follows_p1_contract(admin_a: User, platform_admin: User) -> None:
    body = signed_in(admin_a).get("/me").json()
    assert set(body) == P1_CURRENT_USER and set(body["organization"]) == P1_ORGANIZATION_SUMMARY
    assert body["roles"] == ["ORG_ADMIN"] and "audit.view" in body["permissions"]
    platform = signed_in(platform_admin).get("/me").json()
    assert platform["organization"] is None and "platform.audit" in platform["permissions"]


@pytest.mark.parametrize(("method", "path"), DEFERRED)
def test_deferred_p1_routes_serve_no_simulated_data(
    method: str, path: str, admin_a: User, org_a: Organization
) -> None:
    for api in (signed_in(admin_a), ApiClient()):
        response = api.request(method, path, {} if method != "GET" else None)
        assert response.status_code == 404, (method, path)
        assert response.json() == {"type": "about:blank", "title": "Ressource introuvable", "status": 404}
