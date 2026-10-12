"""Tests de régression de sécurité du backend."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core import mail
from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings
from rest_framework.throttling import SimpleRateThrottle

from apps.audit.integrity import verify_chain
from apps.audit.models import AuditLog
from apps.audit.services import record_event
from apps.audit.tests.test_integrity import tamper
from apps.authentication import services as auth_services
from apps.authentication.tasks import send_password_reset_email
from apps.core.api.policy import MAX_JSON_DEPTH
from apps.core.tests.api_support import ApiClient, signed_in
from apps.organizations.middleware import TenantContextMiddleware
from apps.organizations.models import Organization
from apps.users.models import User
from conftest import owner

pytestmark = pytest.mark.django_db

NUL = "\u0000"


def _access_request(n: int) -> dict[str, Any]:
    return {
        "organization": "Organisme Démo",
        "role": "Chef de projet",
        "name": f"Demandeur {n}",
        "email": f"demandeur{n}@demo.test",
        "request_type": "demonstration",
        "consent": "true",
    }


def _raw_post(api: ApiClient, path: str, raw: str) -> Any:
    return api.client.post(
        f"/api/v1{path}", data=raw, content_type="application/json", headers={"X-CSRFToken": api.csrf()}
    )


# --- Entrées malformées : caractères de contrôle et imbrication excessive -------------------------


@pytest.mark.parametrize(
    ("path", "body", "expected"),
    [
        ("/auth/login", {"email": f"a{NUL}b@demo.test", "password": "x"}, 401),
        ("/auth/login", {"email": "a@demo.test", "password": f"x{NUL}"}, 401),
        ("/auth/password-reset", {"email": f"a{NUL}b@demo.test"}, 202),
        ("/auth/password-reset/confirm", {"token": f"x{NUL}.y", "password": "x"}, 400),
        ("/auth/mfa/verify", {"code": f"12{NUL}456"}, 401),
        ("/public/access-requests", {**_access_request(1), "name": f"x{NUL}"}, 400),
        ("/public/access-requests", {**_access_request(1), f"k{NUL}": "v"}, 400),
    ],
)
def test_control_characters_in_public_input_are_validation_errors(
    path: str, body: dict[str, Any], expected: int
) -> None:
    api = ApiClient()
    api.client.raise_request_exception = False
    response = api.post(path, body)
    assert response.status_code == expected, response.content[:200]
    assert response["Content-Type"] == "application/problem+json" or expected == 202


@pytest.mark.parametrize(("path", "expected"), [("/auth/login", 401), ("/public/access-requests", 400)])
def test_deeply_nested_json_is_rejected_without_server_error(path: str, expected: int) -> None:
    api = ApiClient()
    api.client.raise_request_exception = False
    assert _raw_post(api, path, "[" * 20000).status_code == expected
    nested: Any = "x"
    for _ in range(MAX_JSON_DEPTH + 1):
        nested = {"k": nested}
    assert _raw_post(api, path, json.dumps(nested)).status_code == expected


def test_control_characters_in_query_are_validation_errors(admin_a: User) -> None:
    api = signed_in(admin_a)
    api.client.raise_request_exception = False
    assert api.get(f"/audit-logs?action=a{NUL}b").status_code == 400
    assert api.get(f"/audit-logs?page=1{NUL}").status_code == 400


# --- Limitation de débit du formulaire public -------------------------------------------------------


def test_client_supplied_headers_do_not_bypass_the_public_form_rate_limit() -> None:
    api = ApiClient()
    statuses = [
        api.post(
            "/public/access-requests", _access_request(n), HTTP_X_FORWARDED_FOR=f"198.51.100.{n}"
        ).status_code
        for n in range(1, 8)
    ]
    assert statuses[:5] == [201] * 5
    assert statuses[5:] == [429, 429], statuses


def test_client_address_is_taken_from_the_tcp_peer() -> None:
    assert settings.REST_FRAMEWORK["NUM_PROXIES"] == 0


# --- Erreurs inattendues sous /api/, y compris en mode DEBUG ----------------------------------------


@pytest.mark.urls("apps.core.tests.failing_urls")
@override_settings(DEBUG=True)
def test_unhandled_errors_stay_generic_problems_in_debug() -> None:
    client = Client(raise_request_exception=False)
    for path in ("/api/v1/explodes", "/api/v1/explodes-plain"):
        response = client.get(path)
        assert response.status_code == 500
        assert response["Content-Type"] == "application/problem+json"
        body = response.content.decode()
        assert "Fictif-Secret-Interne" not in body and "Traceback" not in body and "redis://" not in body


def test_framework_errors_under_api_use_the_problem_format() -> None:
    api = ApiClient()
    response = api.post("/health/live")  # vue Django GET uniquement
    assert response.status_code == 405
    assert response["Content-Type"] == "application/problem+json"
    assert response["Allow"] == "GET"
    assert response.json()["title"] == "Méthode non autorisée"


@pytest.mark.parametrize(
    "path", ["/api/v1/health/live", "/api/v1/me", "/api/v1/inconnue", "/api/v1/auth/csrf"]
)
def test_api_responses_carry_json_api_security_headers(path: str) -> None:
    response = Client().get(path)
    assert response["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert response["Cross-Origin-Resource-Policy"] == "same-origin"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"


# --- Réinitialisation de mot de passe : réponse indépendante de l'existence du compte ---------------


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def delay(self, user_id: str | None = None) -> None:
        self.calls.append(user_id)


def test_password_reset_response_does_not_depend_on_account_existence(
    user_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(auth_services, "send_password_reset_email", recorder)
    api = ApiClient()
    for email in (user_a.email, "inconnu@demo-a.rbi.test"):
        response = api.post("/auth/password-reset", {"email": email})
        assert response.status_code == 202
    # Exactement une tâche programmée dans chaque cas ; aucun envoi SMTP pendant la requête.
    assert recorder.calls == [str(user_a.pk), None]
    assert mail.outbox == []


def test_reset_task_checks_the_account_state_before_sending(user_a: User) -> None:
    send_password_reset_email(None)
    send_password_reset_email("pas-un-uuid")
    send_password_reset_email(str(uuid.uuid4()))
    assert mail.outbox == []
    send_password_reset_email(str(user_a.pk))
    assert len(mail.outbox) == 1 and "token=" in mail.outbox[0].body
    with owner():
        User.objects.filter(pk=user_a.pk).update(is_active=False)
    send_password_reset_email(str(user_a.pk))
    assert len(mail.outbox) == 1  # désactivé entre la demande et l'envoi : rien


# --- Points d'entrée serveur : réglages sûrs par défaut ---------------------------------------------


@pytest.mark.parametrize("entry_point", ["config/wsgi.py", "config/asgi.py", "config/celery.py"])
def test_server_entry_points_default_to_safe_settings(entry_point: str) -> None:
    source = (Path(settings.BASE_DIR) / entry_point).read_text(encoding="utf-8")
    assert 'setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")' in source
    assert "settings.development" not in source


# --- Opérations d'audit coûteuses : vérification d'intégrité et export ------------------------------


def _events(org: Organization, actor: User, count: int) -> list[int]:
    for _ in range(count):
        record_event("auth.reauthenticate", outcome="failure", actor_id=actor.pk, organization_id=org.pk)
    with owner(), connection.cursor() as cursor:
        cursor.execute("SELECT id FROM audit_auditlog WHERE organization_id = %s ORDER BY id", [org.pk])
        return [row[0] for row in cursor.fetchall()]


def test_streamed_verification_matches_and_detects_tampering_across_batches(
    admin_a: User, org_a: Organization
) -> None:
    ids = _events(org_a, admin_a, 7)
    with owner():
        whole = verify_chain(str(org_a.pk))
        batched = verify_chain(str(org_a.pk), batch=2)
    assert whole.intact and batched.intact
    assert (batched.checked, batched.head_hash) == (whole.checked, whole.head_hash) == (7, whole.head_hash)
    tamper("UPDATE audit_auditlog SET action = 'auth.login' WHERE id = %s", [ids[4]])  # 3e lot
    with owner():
        report = verify_chain(str(org_a.pk), batch=2)
    assert report.errors == [f"#{ids[4]} : empreinte invalide (contenu modifié)"]


@pytest.mark.parametrize("path", ["/audit-logs/integrity", "/audit-logs/export"])
def test_heavy_audit_operations_have_their_own_rate_limit(
    path: str, admin_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        SimpleRateThrottle, "THROTTLE_RATES", {**SimpleRateThrottle.THROTTLE_RATES, "audit_heavy": "2/min"}
    )
    api = signed_in(admin_a)
    statuses = [api.get(path).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    assert api.get("/audit-logs").status_code == 200  # la consultation paginée n'est pas concernée


# --- Refus du contexte d'organisme au format de l'API -----------------------------------------------


def test_tenant_middleware_refusal_is_a_problem_response(user_a: User, org_a: Organization) -> None:
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    request = RequestFactory().get("/api/v1/organization")
    request.user = user_a
    response = TenantContextMiddleware(lambda r: HttpResponse("atteint"))(request)
    assert response.status_code == 403
    assert response["Content-Type"] == "application/problem+json"
    assert response["Cache-Control"] == "no-store"


# --- Adresse déjà utilisée : refus journalisé -------------------------------------------------------


def test_refused_account_creation_on_a_taken_address_is_audited(
    admin_a: User, user_b: User, org_a: Organization
) -> None:
    response = signed_in(admin_a).post("/users", {"email": user_b.email, "roles": ["AGENT"]})
    assert response.status_code == 400
    assert response.json()["errors"] == {"email": ["Cette adresse ne peut pas être utilisée."]}
    with owner():
        entry = AuditLog.objects.filter(action="user.create", organization_id=org_a.pk).get()
    assert (entry.outcome, entry.actor_id, entry.metadata) == (
        "failure",
        admin_a.pk,
        {"reason": "email_unavailable"},
    )


def test_refused_institutional_admin_on_a_taken_address_is_audited(
    platform_admin: User, user_b: User, org_a: Organization
) -> None:
    response = signed_in(platform_admin).post(
        f"/platform/organizations/{org_a.pk}/institutional-admins", {"email": user_b.email}
    )
    assert response.status_code == 400
    with owner():
        entry = AuditLog.objects.filter(action="user.create_institutional_admin", outcome="failure").get()
    assert (entry.scope, entry.object_type, entry.object_id) == ("platform", "organization", str(org_a.pk))
