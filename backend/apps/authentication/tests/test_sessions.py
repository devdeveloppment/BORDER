"""Sessions : expiration, invalidation (désactivation, suspension, mot de passe, révocation), origine
contrôlée."""

from __future__ import annotations

import time

import pytest
from django.conf import settings

from apps.authentication.services import AUTH_AT_KEY
from apps.organizations.models import Organization
from apps.organizations.tenancy import context_for_user
from apps.users import services as user_services
from apps.users.models import User
from conftest import owner

from .support import PASSWORD, Api, make_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def agent(org_a: Organization) -> User:
    return make_member(org_a, "AGENT", "agent.session@demo-a.rbi.test")


def logged_in(user: User) -> Api:
    api = Api()
    assert api.post("/auth/login", {"email": user.email, "password": PASSWORD}).json() == {
        "step": "AUTHENTICATED"
    }
    assert api.get("/me").status_code == 200
    return api


def test_session_policy_settings() -> None:
    assert settings.SESSION_COOKIE_AGE == 30 * 60  # inactivité 30 min (§19.1)
    assert settings.SESSION_SAVE_EVERY_REQUEST is True  # expiration glissante
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Strict" and settings.CSRF_COOKIE_SAMESITE == "Strict"
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.cache"


def test_inactivity_expiry_is_sliding(agent: User) -> None:
    api = logged_in(agent)
    assert api.client.session.get_expiry_age() == 30 * 60
    cookie = api.client.cookies["rbi_session"]
    assert cookie["max-age"] == "" or int(cookie["max-age"]) <= 30 * 60


def test_absolute_lifetime(agent: User) -> None:
    api = logged_in(agent)
    session = api.client.session
    session[AUTH_AT_KEY] = time.time() - settings.RBI_SESSION_ABSOLUTE_MAX - 1
    session.save()
    assert api.get("/me").status_code == 401


def test_session_not_opened_by_rbi_flow_is_rejected(agent: User) -> None:
    """Une session créée hors du parcours RBI (ex. force_login, sans MFA ni horodatage) n'est pas acceptée."""
    api = Api()
    with owner():
        api.client.force_login(agent, backend="apps.authentication.backends.RBIAuthBackend")
    assert api.get("/me").status_code == 401


def test_deactivation_closes_existing_session(agent: User, admin_a: User) -> None:
    api = logged_in(agent)
    user_services.set_user_active(admin_a, context_for_user(admin_a), agent.pk, active=False)
    assert api.get("/me").status_code == 401


def test_direct_deactivation_also_closes_session(agent: User) -> None:
    api = logged_in(agent)
    with owner():
        User.objects.filter(pk=agent.pk).update(is_active=False)  # même sans passer par les services
    assert api.get("/me").status_code == 401


def test_organization_suspension_closes_session(agent: User, org_a: Organization) -> None:
    api = logged_in(agent)
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    assert api.get("/me").status_code == 401


def test_password_change_keeps_current_session_and_closes_others(agent: User) -> None:
    current, other = logged_in(agent), logged_in(agent)
    new_password = "Nouveau-Mot-De-Passe-2026!"
    assert (
        current.post(
            "/auth/password/change", {"current_password": "faux", "new_password": new_password}
        ).status_code
        == 401
    )
    assert (
        current.post(
            "/auth/password/change", {"current_password": PASSWORD, "new_password": new_password}
        ).status_code
        == 204
    )
    assert current.get("/me").status_code == 200
    assert other.get("/me").status_code == 401
    assert Api().post("/auth/login", {"email": agent.email, "password": PASSWORD}).status_code == 401
    assert Api().post("/auth/login", {"email": agent.email, "password": new_password}).status_code == 200


def test_password_change_enforces_policy(agent: User) -> None:
    api = logged_in(agent)
    for weak in ("court", "password1234", "123456789012", "agent.session"):
        response = api.post("/auth/password/change", {"current_password": PASSWORD, "new_password": weak})
        assert response.status_code == 400, weak
        assert response.json()["errors"]["password"]


def test_revoke_other_sessions(agent: User) -> None:
    current, other = logged_in(agent), logged_in(agent)
    assert current.post("/auth/sessions/revoke-others", {"password": PASSWORD}).status_code == 204
    assert current.get("/me").status_code == 200
    assert other.get("/me").status_code == 401


def test_csrf_required_on_authenticated_actions(agent: User) -> None:
    api = logged_in(agent)
    response = api.post("/auth/sessions/revoke-others", {"password": PASSWORD}, csrf=False)
    assert response.status_code == 403
    assert api.get("/me").status_code == 200
