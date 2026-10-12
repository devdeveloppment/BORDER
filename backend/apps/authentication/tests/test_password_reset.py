"""Réinitialisation du mot de passe (écran 8) : réponse identique, lien unique 30 min, politique,
invalidations."""

from __future__ import annotations

import logging
import re
from unittest import mock

import pytest
from django.core import mail

from apps.authentication.tokens import make_reset_token, reset_tokens
from apps.organizations.models import Organization
from apps.users.models import User
from conftest import owner

from .support import PASSWORD, Api, make_member

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "Reinitialise-Fictif-2026!"
SAME_RESPONSE = {"detail": "Si un compte correspond, un lien de réinitialisation a été envoyé."}


@pytest.fixture
def agent(org_a: Organization) -> User:
    return make_member(org_a, "AGENT", "agent.reset@demo-a.rbi.test")


def token_from_mail() -> str:
    match = re.search(r"token=(\S+)", str(mail.outbox[-1].body))
    assert match
    return match.group(1)


def test_identical_response_whatever_the_account(api: Api, agent: User, org_a: Organization) -> None:
    inactive = make_member(org_a, "AGENT", "inactif@demo-a.rbi.test")
    inactive.is_active = False
    with owner():
        inactive.save()
    for email in (agent.email, "inconnu@demo-a.rbi.test", inactive.email):
        response = api.post("/auth/password-reset", {"email": email})
        assert (response.status_code, response.json()) == (202, SAME_RESPONSE)
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [agent.email]


def test_no_link_for_suspended_organization(api: Api, agent: User, org_a: Organization) -> None:
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    assert api.post("/auth/password-reset", {"email": agent.email}).json() == SAME_RESPONSE
    assert mail.outbox == []


def test_rate_limited_silently(api: Api, agent: User) -> None:
    for _ in range(5):
        assert api.post("/auth/password-reset", {"email": agent.email}).json() == SAME_RESPONSE
    assert len(mail.outbox) == 3  # 3 envois par heure et par identifiant ; réponse inchangée au-delà


def test_full_reset_flow(api: Api, agent: User) -> None:
    session = Api()
    session.post("/auth/login", {"email": agent.email, "password": PASSWORD})
    api.post("/auth/password-reset", {"email": agent.email})
    token = token_from_mail()
    assert PASSWORD not in mail.outbox[-1].body
    assert (
        api.post("/auth/password-reset/confirm", {"token": token, "password": NEW_PASSWORD}).status_code
        == 204
    )
    assert session.get("/me").status_code == 401  # sessions existantes fermées
    assert Api().post("/auth/login", {"email": agent.email, "password": PASSWORD}).status_code == 401
    assert Api().post("/auth/login", {"email": agent.email, "password": NEW_PASSWORD}).json() == {
        "step": "AUTHENTICATED"
    }
    # Lien à usage unique.
    reused = api.post("/auth/password-reset/confirm", {"token": token, "password": "Autre-Fictif-2026-mdp!"})
    assert reused.status_code == 400 and reused.json()["title"] == "Lien expiré ou invalide"


@pytest.mark.parametrize("token", ["", "abc", "Zm9v.1-2", "not-a-uuid.xyz-abc", "a" * 300])
def test_invalid_tokens(api: Api, token: str) -> None:
    response = api.post("/auth/password-reset/confirm", {"token": token, "password": NEW_PASSWORD})
    assert response.status_code == 400 and response.json()["title"] == "Lien expiré ou invalide"


def test_link_expires_after_30_minutes(api: Api, agent: User) -> None:
    token = make_reset_token(agent)
    later = reset_tokens._now().timestamp() + 31 * 60
    with mock.patch.object(
        type(reset_tokens), "_now", return_value=__import__("datetime").datetime.fromtimestamp(later)
    ):
        response = api.post("/auth/password-reset/confirm", {"token": token, "password": NEW_PASSWORD})
    assert response.status_code == 400


def test_policy_enforced_on_reset(api: Api, agent: User) -> None:
    token = make_reset_token(agent)
    response = api.post("/auth/password-reset/confirm", {"token": token, "password": "trop-court"})
    assert response.status_code == 400
    assert response.json()["title"] == "Mot de passe non conforme"
    assert any("12" in message for message in response.json()["errors"]["password"])
    # Le jeton reste utilisable après un refus de politique (mot de passe inchangé).
    assert (
        api.post("/auth/password-reset/confirm", {"token": token, "password": NEW_PASSWORD}).status_code
        == 204
    )


def test_reset_also_cancels_a_pending_mfa_step(api: Api, org_a: Organization) -> None:
    supervisor = make_member(org_a, "SUPERVISOR", "superviseur.reset@demo-a.rbi.test")
    pending = Api()
    pending.post("/auth/login", {"email": supervisor.email, "password": PASSWORD})
    api.post(
        "/auth/password-reset/confirm", {"token": make_reset_token(supervisor), "password": NEW_PASSWORD}
    )
    assert pending.post("/auth/mfa/enroll").status_code == 401


def test_token_never_logged(api: Api, agent: User, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    api.post("/auth/password-reset", {"email": agent.email})
    token = token_from_mail()
    api.post("/auth/password-reset/confirm", {"token": token, "password": NEW_PASSWORD})
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert token not in logged and token.split(".")[1] not in logged
    assert NEW_PASSWORD not in logged
