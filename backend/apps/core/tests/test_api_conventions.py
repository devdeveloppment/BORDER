"""Conventions transverses de l'API v1 (P2.8, ADR 0010) : erreurs, tailles, CSRF, en-têtes, débit."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from django.test import Client

from apps.core.api.policy import BoundedJSONParser, RequestTooLarge
from apps.organizations.models import AccessRequest, Organization
from apps.users.models import User
from conftest import owner

from .api_support import ApiClient, signed_in

pytestmark = pytest.mark.django_db

FORM = {
    "organization": "Organisme Demandeur Fictif",
    "role": "Directeur",
    "name": "Personne Fictive",
    "email": "contact@demandeur.rbi.test",
    "phone": "",
    "request_type": "demonstration",
    "message": "",
    "consent": "true",
}


def test_unknown_route_is_a_json_404() -> None:
    for api in (ApiClient(),):
        response = api.get("/inexistant")
        assert response.status_code == 404
        assert response.json() == {"type": "about:blank", "title": "Ressource introuvable", "status": 404}


def test_unknown_route_is_json_even_in_debug_mode(settings: Any) -> None:
    """En développement (DEBUG), Django renverrait une page HTML listant toutes les routes."""
    settings.DEBUG = True
    response = ApiClient().get("/inexistant")
    assert response.status_code == 404 and response["Content-Type"] == "application/problem+json"
    assert b"api/v1/" not in response.content


@pytest.mark.urls("apps.core.tests.failing_urls")
def test_unexpected_exception_is_a_generic_500_without_internal_detail() -> None:
    client = Client(raise_request_exception=False)
    for path in ("/api/v1/explodes", "/api/v1/explodes-plain"):
        response = client.get(path)
        assert response.status_code == 500
        assert response.json() == {
            "type": "about:blank",
            "title": "Erreur interne",
            "status": 500,
            "detail": "Une erreur inattendue s'est produite.",
        }
        body = response.content.decode()
        assert "Fictif-Secret-Interne" not in body and "/opt/venv" not in body and "Traceback" not in body
        assert response["X-Request-ID"]  # permet de retrouver la trace dans les journaux du serveur


def test_announced_body_too_large_is_refused_before_reading() -> None:
    api = ApiClient()
    big = {"email": "x@demo.rbi.test", "password": "p" * (70 * 1024)}
    response = api.post("/auth/login", big)
    assert response.status_code == 413
    assert response.json()["title"] == "Requête trop volumineuse"


def test_parser_bounds_a_body_without_content_length(settings: Any) -> None:
    settings.RBI_API_MAX_BODY_BYTES = 100
    with pytest.raises(RequestTooLarge):
        BoundedJSONParser().parse(io.BytesIO(json.dumps({"a": "b" * 200}).encode()), "application/json")
    assert BoundedJSONParser().parse(io.BytesIO(b'{"a": 1}'), "application/json") == {"a": 1}


def test_non_json_body_is_refused() -> None:
    api = ApiClient()
    response = api.client.post(
        "/api/v1/public/access-requests",
        data="organization=x",
        content_type="application/x-www-form-urlencoded",
        headers={"X-CSRFToken": api.csrf()},
    )
    assert response.status_code == 415
    assert not AccessRequest.objects.exists()


def test_malformed_json_is_a_400_outside_the_login_flow() -> None:
    api = ApiClient()
    response = api.client.post(
        "/api/v1/public/access-requests",
        data="{pas du json",
        content_type="application/json",
        headers={"X-CSRFToken": api.csrf()},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Corps de requête JSON invalide."


def test_json_array_is_refused() -> None:
    response = ApiClient().post("/public/access-requests", [FORM])
    assert response.status_code == 400


def test_csrf_is_required_on_public_and_authenticated_writes(admin_a: User) -> None:
    anonymous = ApiClient()
    assert anonymous.request("POST", "/public/access-requests", FORM, csrf=False).status_code == 403
    signed = signed_in(admin_a)
    response = signed.request("POST", "/users", {"email": "nouveau@demo-a.rbi.test"}, csrf=False)
    assert response.status_code == 403
    assert response.json()["title"] == "Requête refusée"  # vue d'échec CSRF (P2.5), sans cause technique
    with owner():
        assert not User.objects.filter(email="nouveau@demo-a.rbi.test").exists()


def test_every_api_response_is_not_cacheable_and_correlated(admin_a: User) -> None:
    api = signed_in(admin_a)
    for response in (api.get("/me"), api.get("/users"), api.get("/organization"), ApiClient().get("/me")):
        assert response["Cache-Control"] == "no-store"
        assert len(response["X-Request-ID"]) == 36


def test_dates_are_iso_8601_utc(admin_a: User) -> None:
    response = signed_in(admin_a).get("/organization").json()
    assert response["created_at"].endswith("Z")


def test_access_request_form_is_rate_limited_per_address() -> None:
    api = ApiClient()
    codes = [
        api.post("/public/access-requests", {**FORM, "email": f"contact{i}@demandeur.rbi.test"}).status_code
        for i in range(6)
    ]
    assert codes == [201] * 5 + [429]
    response = api.post("/public/access-requests", FORM)
    assert response.status_code == 429 and int(response["Retry-After"]) > 0
    with owner():
        assert AccessRequest.objects.count() == 5


def test_authenticated_requests_are_rate_limited_per_account(
    monkeypatch: pytest.MonkeyPatch, admin_a: User
) -> None:
    from rest_framework.throttling import SimpleRateThrottle

    # Taux réduit pour ce test seulement (monkeypatch restaure la valeur d'origine, même en cas d'échec).
    monkeypatch.setattr(
        SimpleRateThrottle, "THROTTLE_RATES", {**SimpleRateThrottle.THROTTLE_RATES, "user": "3/min"}
    )
    api = signed_in(admin_a)
    assert [api.get("/roles").status_code for _ in range(4)] == [200, 200, 200, 429]


def test_access_request_creates_no_account_and_returns_p1_contract(org_a: Organization) -> None:
    response = ApiClient().post("/public/access-requests", FORM)
    assert response.status_code == 201 and response.json() == {"detail": "Demande enregistrée."}
    with owner():
        request = AccessRequest.objects.get(email=FORM["email"])
        assert (request.organization_name, request.requester_role, request.status) == (
            FORM["organization"],
            FORM["role"],
            "EN_ATTENTE",
        )
        assert not User.objects.filter(email=FORM["email"]).exists()


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"consent": "false"}, "consent"),
        ({"email": "pas-une-adresse"}, "email"),
        ({"organization": ""}, "organization"),
        ({"request_type": "acces_total"}, "request_type"),
        ({"organization_id": "11111111-1111-1111-1111-111111111111", "consent": "false"}, "consent"),
    ],
)
def test_access_request_errors_use_p1_field_names(change: dict[str, str], field: str) -> None:
    response = ApiClient().post("/public/access-requests", {**FORM, **change})
    assert response.status_code == 400
    assert field in response.json()["errors"]
    with owner():
        assert not AccessRequest.objects.exists()
