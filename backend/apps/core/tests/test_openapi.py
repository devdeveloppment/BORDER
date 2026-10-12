"""Contrat OpenAPI versionné (P2.8) : généré, validé, identique au fichier de référence, fidèle aux
politiques.

Toute évolution de l'API modifie le schéma généré : le fichier ``openapi/rbi-api-v1.yaml`` doit alors être
régénéré VOLONTAIREMENT (commande dans backend/README.md) et revu dans le diff. Une dérive involontaire fait
échouer ``test_committed_schema_is_up_to_date``.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.conf import settings
from django.core.management import call_command

from apps.users.models import User

from .api_support import ApiClient, signed_in
from .test_api_routes import EXPECTED, PLAIN_DJANGO_PUBLIC

SCHEMA_FILE = Path(settings.BASE_DIR) / "openapi" / "rbi-api-v1.yaml"


@pytest.fixture(scope="module")
def generated() -> str:
    out = io.StringIO()
    call_command("spectacular", "--validate", "--fail-on-warn", stdout=out)  # erreur si invalide ou ambigu
    return out.getvalue()


def test_committed_schema_is_up_to_date(generated: str) -> None:
    assert SCHEMA_FILE.read_text(encoding="utf-8") == generated, (
        "Schéma OpenAPI modifié : régénérer openapi/rbi-api-v1.yaml et relire le diff."
    )


def test_every_documented_operation_carries_the_real_policy(generated: str) -> None:
    schema: dict[str, Any] = yaml.safe_load(generated)
    documented: dict[str, dict[str, str]] = {}
    for path, operations in schema["paths"].items():
        route = "api/v1" + path.removeprefix("/api/v1")
        for method, operation in operations.items():
            documented.setdefault(route, {})[method.upper()] = operation["x-rbi-policy"].removeprefix(
                "permission:"
            )
    expected = {
        route.replace("<uuid:", "{").replace("<str:", "{").replace(">", "}"): policies
        for route, policies in EXPECTED.items()
        if route not in PLAIN_DJANGO_PUBLIC and route != "api/v1/schema"
    }
    assert documented == expected


def test_public_operations_require_no_authentication_and_others_the_session(generated: str) -> None:
    schema: dict[str, Any] = yaml.safe_load(generated)
    assert schema["components"]["securitySchemes"]["sessionCookie"]["name"] == settings.SESSION_COOKIE_NAME
    for operations in schema["paths"].values():
        for operation in operations.values():
            if operation["x-rbi-policy"] == "public":
                assert operation.get("security", []) in ([], [{}])
            else:
                assert operation["security"] == [{"sessionCookie": []}]


def test_schema_exposes_no_maintenance_endpoint_nor_secret(generated: str) -> None:
    paths = set(yaml.safe_load(generated)["paths"])
    assert not {
        p for p in paths if p.split("/")[3] in ("health", "schema")
    }  # sondes et schéma : hors contrat
    lowered = generated.lower()
    for forbidden in ("audit_verify", "create_super_admin", "reset_user_mfa", "rbi_owner", "fictif-"):
        assert forbidden not in lowered, forbidden


@pytest.mark.django_db
def test_schema_endpoint_is_reserved_to_authenticated_users(admin_a: User) -> None:
    assert ApiClient().get("/schema").status_code == 401
    response = signed_in(admin_a).get("/schema")
    assert response.status_code == 200 and b"openapi: 3" in response.content
