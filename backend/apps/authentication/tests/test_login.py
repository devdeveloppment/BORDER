"""Connexion par mot de passe : parcours HTTP complets, CSRF réel, messages génériques, limitation des
tentatives."""

from __future__ import annotations

import json
import logging
import re

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from apps.authentication import throttling
from apps.organizations.models import Organization
from apps.users.models import User
from conftest import owner

from .support import PASSWORD, Api, make_member

pytestmark = pytest.mark.django_db

GENERIC_401 = {"type": "about:blank", "title": "Identifiants incorrects", "status": 401}


@pytest.fixture
def agent(org_a: Organization) -> User:
    return make_member(org_a, "AGENT", "agent.login@demo-a.rbi.test")


# --- CSRF ------------------------------------------------------------------------------------


def test_csrf_cookie_then_login(api: Api, agent: User) -> None:
    token = api.csrf()
    assert token
    assert api.client.cookies["csrftoken"]["samesite"] == "Strict"


def test_login_refused_without_csrf_token(api: Api, agent: User) -> None:
    api.csrf()
    response = api.post("/auth/login", {"email": agent.email, "password": PASSWORD}, csrf=False)
    assert response.status_code == 403
    assert response["Content-Type"] == "application/problem+json"
    assert response.json()["title"] == "Requête refusée"  # aucune explication technique de la cause
    assert api.session_key is None or api.get("/me").status_code == 401


def test_login_refused_with_forged_csrf_token(api: Api, agent: User) -> None:
    api.csrf()
    response = api.post(
        "/auth/login",
        {"email": agent.email, "password": PASSWORD},
        csrf=False,
        headers={"X-CSRFToken": "x" * 32},
    )
    assert response.status_code == 403


# --- Connexion -------------------------------------------------------------------------------


def test_successful_login_without_mfa(api: Api, agent: User, org_a: Organization) -> None:
    api.csrf()
    anonymous_key = api.client.cookies.get("rbi_session")
    response = api.post("/auth/login", {"email": "  Agent.Login@Demo-A.rbi.test ", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"step": "AUTHENTICATED"}
    cookie = api.client.cookies["rbi_session"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Strict"
    assert anonymous_key is None or anonymous_key.value != cookie.value  # nouvelle clé : pas de fixation
    me = api.get("/me").json()
    assert me["email"] == agent.email
    assert me["roles"] == ["AGENT"]
    assert me["organization"]["id"] == str(org_a.pk)
    assert me["mfa_required"] is False and me["mfa_enabled"] is False
    with owner():
        agent.refresh_from_db()
    assert agent.last_login is not None


def test_password_is_hashed_with_argon2(agent: User) -> None:
    assert agent.password.startswith("argon2$")


@pytest.mark.parametrize(
    "case",
    ["wrong_password", "unknown_email", "inactive_account", "empty_password", "malformed_body"],
)
def test_failures_are_generic(api: Api, agent: User, case: str) -> None:
    if case == "inactive_account":
        agent.is_active = False
        with owner():
            agent.save()
    body: object = {
        "wrong_password": {"email": agent.email, "password": "Mauvais-mot-de-passe-2026"},
        "unknown_email": {"email": "inconnu@demo-a.rbi.test", "password": PASSWORD},
        "inactive_account": {"email": agent.email, "password": PASSWORD},
        "empty_password": {"email": agent.email, "password": ""},
        "malformed_body": ["pas", "un", "objet"],
    }[case]
    api.csrf()
    response = api.client.post(
        "/api/v1/auth/login",
        data=json.dumps(body),
        content_type="application/json",
        headers={"X-CSRFToken": api.client.cookies["csrftoken"].value},
    )
    assert response.status_code == 401
    assert response.json() == GENERIC_401  # identique : ne révèle pas l'existence ni l'état du compte
    assert response["Content-Type"] == "application/problem+json"
    assert api.get("/me").status_code == 401


def test_suspended_organization_message_only_after_valid_password(
    api: Api, agent: User, org_a: Organization
) -> None:
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    wrong = api.post("/auth/login", {"email": agent.email, "password": "Mauvais-mot-de-passe-2026"})
    assert wrong.status_code == 401 and wrong.json() == GENERIC_401
    right = api.post("/auth/login", {"email": agent.email, "password": PASSWORD})
    assert right.status_code == 403
    assert right.json()["title"] == "Organisme suspendu"
    assert api.get("/me").status_code == 401


@pytest.mark.parametrize("status", ["EN_ATTENTE", "AUTORISEE", "ARCHIVEE"])
def test_non_active_organization_refused_generically(
    api: Api, agent: User, org_a: Organization, status: str
) -> None:
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=status)
    response = api.post("/auth/login", {"email": agent.email, "password": PASSWORD})
    assert response.status_code == 401 and response.json() == GENERIC_401


def test_platform_account_can_log_in(api: Api, platform_user_without_permission: User) -> None:
    platform_user_without_permission.set_password(PASSWORD)
    with owner():
        platform_user_without_permission.save()
    response = api.post(
        "/auth/login", {"email": platform_user_without_permission.email, "password": PASSWORD}
    )
    assert response.json() == {"step": "AUTHENTICATED"}
    me = api.get("/me").json()
    assert me["organization"] is None and me["roles"] == [] and me["permissions"] == []


# --- Limitation des tentatives ------------------------------------------------------------------


def test_progressive_lock_after_five_failures(api: Api, agent: User) -> None:
    for _ in range(throttling.LOGIN_FAILURES_BEFORE_LOCK):
        assert (
            api.post("/auth/login", {"email": agent.email, "password": "Mauvais-2026-xx"}).status_code == 401
        )
    locked = api.post("/auth/login", {"email": agent.email, "password": PASSWORD})  # même le bon mot de passe
    assert locked.status_code == 429
    assert int(locked["Retry-After"]) >= 1
    assert locked.json()["title"] == "Trop de tentatives"
    assert api.get("/me").status_code == 401


def test_unknown_account_is_locked_the_same_way(api: Api) -> None:
    """Aucune énumération : un e-mail inexistant suit exactement les mêmes règles."""
    for _ in range(throttling.LOGIN_FAILURES_BEFORE_LOCK):
        assert (
            api.post("/auth/login", {"email": "fantome@demo-a.rbi.test", "password": "x"}).status_code == 401
        )
    assert api.post("/auth/login", {"email": "fantome@demo-a.rbi.test", "password": "x"}).status_code == 429


def test_lock_duration_grows(agent: User) -> None:
    for _ in range(throttling.LOGIN_FAILURES_BEFORE_LOCK):
        throttling.register_login_failure(agent.email, "198.51.100.7")
    first = throttling.login_lock(agent.email, "198.51.100.7")
    throttling.register_login_failure(agent.email, "198.51.100.7")
    second = throttling.login_lock(agent.email, "198.51.100.7")
    assert first is not None and second is not None and second.retry_after > first.retry_after


def test_ip_limit_across_accounts(api: Api, agent: User) -> None:
    for i in range(throttling.IP_FAILURES_LIMIT):
        api.post("/auth/login", {"email": f"essai{i}@demo-a.rbi.test", "password": "x"})
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).status_code == 429


def test_success_resets_failure_counter(api: Api, agent: User) -> None:
    for _ in range(throttling.LOGIN_FAILURES_BEFORE_LOCK - 1):
        api.post("/auth/login", {"email": agent.email, "password": "Mauvais-2026-xx"})
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).json() == {
        "step": "AUTHENTICATED"
    }
    api.post("/auth/logout")
    assert api.post("/auth/login", {"email": agent.email, "password": "Mauvais-2026-xx"}).status_code == 401


# --- Déconnexion et refus par défaut ------------------------------------------------------------


def test_logout(api: Api, agent: User) -> None:
    api.post("/auth/login", {"email": agent.email, "password": PASSWORD})
    old_key = api.session_key
    assert api.get("/me").status_code == 200
    assert api.post("/auth/logout").status_code == 204
    assert api.get("/me").status_code == 401
    from django.contrib.sessions.backends.cache import SessionStore

    assert old_key is not None and not SessionStore(session_key=old_key).exists(old_key)
    assert api.post("/auth/logout").status_code == 204  # idempotent


def _iter_patterns(resolver: URLResolver, prefix: str = "") -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            found += _iter_patterns(pattern, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            found.append((prefix + str(pattern.pattern), pattern.callback))
    return found


def test_every_non_public_route_requires_authentication(api: Api) -> None:
    """Refus par défaut : toute route non marquée publique répond 401 à un anonyme, quelle que soit la
    méthode."""
    protected = [
        (route, view)
        for route, view in _iter_patterns(get_resolver())
        if not getattr(view, "rbi_public", False)
    ]
    assert len(protected) >= 7
    api.csrf()
    for route, _ in protected:
        path = re.sub(r"<uuid:\w+>", "00000000-0000-0000-0000-000000000001", "/" + route)
        path = re.sub(r"<str:\w+>", "AGENT", path)  # P2.8 : routes paramétrées
        for method in ("get", "post"):
            response = getattr(api.client, method)(
                path, headers={"X-CSRFToken": api.client.cookies["csrftoken"].value}
            )
            assert response.status_code == 401, (method, route)
            assert response.json()["title"] == "Authentification requise"


def test_public_routes_are_exactly_the_expected_ones() -> None:
    public = {route for route, view in _iter_patterns(get_resolver()) if getattr(view, "rbi_public", False)}
    assert public == {
        "api/v1/health/live",
        "api/v1/health/ready",
        "api/v1/auth/csrf",
        "api/v1/auth/login",
        "api/v1/auth/mfa/enroll",
        "api/v1/auth/mfa/verify",
        "api/v1/auth/logout",
        "api/v1/auth/password-reset",
        "api/v1/auth/password-reset/confirm",
        "api/v1/public/access-requests",  # P2.8 : formulaire public (écran 5)
    }


# --- Aucune fuite de secret ---------------------------------------------------------------------


def test_no_secret_in_responses_or_logs(api: Api, agent: User, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    bad = "Secret-Errone-2026-zz"
    bodies = [
        api.post("/auth/login", {"email": agent.email, "password": bad}).content,
        api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).content,
        api.get("/me").content,
    ]
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (PASSWORD, bad):
        assert secret not in logged
        assert all(secret.encode() not in body for body in bodies)
    assert agent.password not in logged  # pas même le hachage
    audit = [json.loads(r.getMessage()) for r in caplog.records if r.name == "rbi.audit"]
    assert audit and all(agent.email not in json.dumps(event) for event in audit)
