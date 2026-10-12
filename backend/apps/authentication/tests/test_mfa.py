"""MFA TOTP : enrôlement, vérification, rejeu, expiration, verrouillage, codes de secours, contournements."""

from __future__ import annotations

import io
import logging
import time

import pytest
from django.conf import settings
from django.core.management import call_command
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.authentication import services, throttling
from apps.authentication.models import MfaBackupCode
from apps.organizations.models import Organization
from apps.organizations.tenancy import context_for_user
from apps.users.models import User
from conftest import grant_role, owner

from .support import PASSWORD, Api, enroll, login_with_mfa, make_member, totp_code

pytestmark = pytest.mark.django_db

PROTECTED = ("/me",)
PROTECTED_POST = (
    "/auth/password/change",
    "/auth/mfa/backup-codes",
    "/auth/sessions/revoke-others",
    "/auth/mfa/disable",
)


@pytest.fixture
def supervisor(org_a: Organization) -> User:
    return make_member(org_a, "SUPERVISOR", "superviseur.mfa@demo-a.rbi.test")


def assert_not_authenticated(api: Api) -> None:
    for path in PROTECTED:
        assert api.get(path).status_code == 401, path
    for path in PROTECTED_POST:
        assert api.post(path, {"password": PASSWORD}).status_code == 401, path


# --- Enrôlement ------------------------------------------------------------------------------


def test_totp_secret_is_returned_once_and_never_logged(
    api: Api, supervisor: User, caplog: pytest.LogCaptureFixture
) -> None:
    """Le secret d'enrôlement n'apparaît ni dans les journaux, ni dans les réponses suivantes."""
    caplog.set_level(logging.DEBUG)
    api.post("/auth/login", {"email": supervisor.email, "password": PASSWORD})
    secret = api.post("/auth/mfa/enroll").json()["secret"]
    relogin = api.post("/auth/login", {"email": supervisor.email, "password": PASSWORD}).content
    later = [relogin, api.get("/me").content]
    logged = "\n".join(record.getMessage() for record in caplog.records)
    # Seuls les emplacements fuyants sont nommés : la valeur du secret ne sort jamais dans les tests.
    exposed = []
    if secret in logged:
        exposed.append("journaux")
    if any(secret.encode() in body for body in later):
        exposed.append("réponses suivantes")
    assert not exposed, f"secret TOTP exposé dans : {', '.join(exposed)}"


def test_first_login_requires_enrollment_and_grants_nothing_before(api: Api, supervisor: User) -> None:
    assert api.post("/auth/login", {"email": supervisor.email, "password": PASSWORD}).json() == {
        "step": "MFA_ENROLLMENT_REQUIRED"
    }
    assert_not_authenticated(api)  # mot de passe seul : aucun accès
    provisioning = api.post("/auth/mfa/enroll")
    assert provisioning.status_code == 200 and "no-store" in provisioning["Cache-Control"]
    body = provisioning.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/") and "RIZTECH" in body["otpauth_uri"]
    assert len(body["secret"]) >= 32
    assert_not_authenticated(api)  # enrôlement commencé, non confirmé : toujours aucun accès
    with owner():
        device = TOTPDevice.objects.get(user=supervisor, confirmed=False)
    verified = api.post("/auth/mfa/verify", {"code": totp_code(device)})
    assert verified.status_code == 200
    assert verified.json()["step"] == "AUTHENTICATED"
    codes = verified.json()["backup_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    with owner():
        assert not MfaBackupCode.objects.filter(code_hash__in=codes).exists()  # stockés hachés
    me = api.get("/me").json()
    assert me["mfa_enabled"] is True and me["mfa_required"] is True
    assert "alerts.decide" in me["permissions"]


def test_enroll_only_during_enrollment_step(api: Api, supervisor: User) -> None:
    assert api.post("/auth/mfa/enroll").status_code == 401  # aucune connexion en cours
    enroll(api, supervisor)
    api.post("/auth/logout")
    api.post("/auth/login", {"email": supervisor.email, "password": PASSWORD})  # désormais MFA_REQUIRED
    assert api.post("/auth/mfa/enroll").status_code == 403  # pas de second appareil par ce biais


def test_verify_without_password_step_is_refused(api: Api, supervisor: User) -> None:
    response = api.post("/auth/mfa/verify", {"code": "123456"})
    assert response.status_code == 401 and response.json()["title"] == "Session expirée"


# --- Vérification ----------------------------------------------------------------------------


@pytest.fixture
def enrolled(api: Api, supervisor: User) -> tuple[User, list[str]]:
    codes = enroll(api, supervisor)
    api.post("/auth/logout")
    return supervisor, codes


def test_second_login_requires_code(api: Api, enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    assert api.post("/auth/login", {"email": user.email, "password": PASSWORD}).json() == {
        "step": "MFA_REQUIRED"
    }
    assert_not_authenticated(api)
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    assert api.post("/auth/mfa/verify", {"code": totp_code(device, 1)}).status_code == 200
    assert api.get("/me").status_code == 200


@pytest.mark.parametrize("code", ["000000", "12345", "abcdef", "", "1234567"])
def test_invalid_code(api: Api, enrolled: tuple[User, list[str]], code: str) -> None:
    user, _ = enrolled
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    response = api.post("/auth/mfa/verify", {"code": code})
    assert response.status_code == 400 and response.json()["title"] == "Code invalide ou expiré"
    assert api.get("/me").status_code == 401


def test_expired_code(api: Api, enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    assert api.post("/auth/mfa/verify", {"code": totp_code(device, -3)}).status_code == 400  # 90 s : expiré
    assert api.get("/me").status_code == 401


def test_code_cannot_be_replayed(enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    code = totp_code(device, 1)
    first, second = Api(), Api()
    first.post("/auth/login", {"email": user.email, "password": PASSWORD})
    assert first.post("/auth/mfa/verify", {"code": code}).status_code == 200
    second.post("/auth/login", {"email": user.email, "password": PASSWORD})
    assert second.post("/auth/mfa/verify", {"code": code}).status_code == 400  # même code : rejeu refusé


def test_five_invalid_codes_lock_mfa(api: Api, enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    for _ in range(throttling.MFA_FAILURES_BEFORE_LOCK - 1):
        assert api.post("/auth/mfa/verify", {"code": "000000"}).status_code == 400
    locked = api.post("/auth/mfa/verify", {"code": "000000"})
    assert locked.status_code == 429 and "Retry-After" in locked
    # L'étape intermédiaire est détruite, et le compte reste verrouillé même après un nouveau mot de passe
    # correct.
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    assert api.post("/auth/mfa/verify", {"code": totp_code(device, 1)}).status_code == 401
    assert api.post("/auth/login", {"email": user.email, "password": PASSWORD}).status_code == 429
    assert api.get("/me").status_code == 401


def test_pending_step_expires(api: Api, enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    session = api.client.session
    session[services.PENDING_KEY]["at"] = time.time() - settings.RBI_MFA_PENDING_TTL - 1
    session.save()
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    assert api.post("/auth/mfa/verify", {"code": totp_code(device, 1)}).status_code == 401


def test_pending_step_invalidated_by_security_event(api: Api, enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    user.rotate_security_stamp()  # ex. mot de passe réinitialisé entre-temps
    with owner():
        user.save()
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    assert api.post("/auth/mfa/verify", {"code": totp_code(device, 1)}).status_code == 401


def test_pending_step_refused_if_account_disabled_meanwhile(
    api: Api, enrolled: tuple[User, list[str]]
) -> None:
    user, _ = enrolled
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    with owner():
        User.objects.filter(pk=user.pk).update(is_active=False)
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    assert api.post("/auth/mfa/verify", {"code": totp_code(device, 1)}).status_code == 401


# --- Codes de secours ------------------------------------------------------------------------


def test_backup_code_works_once(api: Api, enrolled: tuple[User, list[str]]) -> None:
    user, codes = enrolled
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    assert api.post("/auth/mfa/verify", {"code": codes[0].lower()}).status_code == 200
    api.post("/auth/logout")
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    assert api.post("/auth/mfa/verify", {"code": codes[0]}).status_code == 400
    assert api.post("/auth/mfa/verify", {"code": codes[1]}).status_code == 200


def test_regenerate_backup_codes_requires_password_and_revokes_old(
    api: Api, enrolled: tuple[User, list[str]]
) -> None:
    user, old = enrolled
    login_with_mfa(api, user)
    assert api.post("/auth/mfa/backup-codes", {"password": "Mauvais-2026-xx"}).status_code == 401
    fresh = api.post("/auth/mfa/backup-codes", {"password": PASSWORD}).json()["backup_codes"]
    assert set(fresh).isdisjoint(old)
    api.post("/auth/logout")
    api.post("/auth/login", {"email": user.email, "password": PASSWORD})
    assert api.post("/auth/mfa/verify", {"code": old[2]}).status_code == 400


# --- MFA obligatoire / contournements ----------------------------------------------------------


def test_promotion_to_mfa_role_terminates_session_without_mfa(api: Api, org_a: Organization) -> None:
    agent = make_member(org_a, "AGENT", "agent.promu@demo-a.rbi.test")
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).json() == {
        "step": "AUTHENTICATED"
    }
    assert api.get("/me").status_code == 200
    grant_role(agent, "SUPERVISOR")  # rôle à MFA obligatoire attribué pendant la session
    assert api.get("/me").status_code == 401  # session fermée : MFA désormais exigée
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).json() == {
        "step": "MFA_ENROLLMENT_REQUIRED"
    }


def test_optional_mfa_enable_and_disable_for_agent(api: Api, org_a: Organization) -> None:
    agent = make_member(org_a, "AGENT", "agent.mfa@demo-a.rbi.test")
    api.post("/auth/login", {"email": agent.email, "password": PASSWORD})
    assert api.post("/auth/mfa/totp/renew", {"password": "Mauvais-2026-xx"}).status_code == 401
    assert api.post("/auth/mfa/totp/renew", {"password": PASSWORD}).status_code == 200
    with owner():
        device = TOTPDevice.objects.get(user=agent, confirmed=False)
    confirmed = api.post("/auth/mfa/totp/renew/confirm", {"code": totp_code(device)})
    assert confirmed.status_code == 200 and len(confirmed.json()["backup_codes"]) == 10
    assert api.get("/me").json()["mfa_enabled"] is True  # session courante conservée
    api.post("/auth/logout")
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).json() == {
        "step": "MFA_REQUIRED"
    }
    assert api.post("/auth/mfa/verify", {"code": totp_code(device, 1)}).status_code == 200
    assert api.post("/auth/mfa/disable", {"password": PASSWORD}).status_code == 204
    api.post("/auth/logout")
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).json() == {
        "step": "AUTHENTICATED"
    }


def test_mandatory_mfa_cannot_be_disabled(api: Api, enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    login_with_mfa(api, user)
    assert api.post("/auth/mfa/disable", {"password": PASSWORD}).status_code == 403
    with owner():
        assert TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def test_totp_renewal_replaces_device_only_after_confirmation(
    api: Api, enrolled: tuple[User, list[str]]
) -> None:
    user, _ = enrolled
    login_with_mfa(api, user)
    with owner():
        old = TOTPDevice.objects.get(user=user, confirmed=True)
    api.post("/auth/mfa/totp/renew", {"password": PASSWORD})
    assert api.post("/auth/mfa/totp/renew/confirm", {"code": "000000"}).status_code == 400
    with owner():
        assert TOTPDevice.objects.filter(
            pk=old.pk, confirmed=True
        ).exists()  # ancien appareil toujours valide
    with owner():
        new = TOTPDevice.objects.get(user=user, confirmed=False)
    time.sleep(1.1)  # ralentissement de django-otp après l'échec ci-dessus
    assert api.post("/auth/mfa/totp/renew/confirm", {"code": totp_code(new)}).status_code == 200
    with owner():
        assert list(TOTPDevice.objects.filter(user=user).values_list("pk", flat=True)) == [new.pk]


# --- Récupération par un administrateur ou hors bande ------------------------------------------


def test_admin_resets_mfa_and_closes_sessions(admin_a: User, enrolled: tuple[User, list[str]]) -> None:
    user, _ = enrolled
    session = Api()
    login_with_mfa(session, user)
    assert session.get("/me").status_code == 200
    services.reset_user_mfa(admin_a, context_for_user(admin_a), user.pk)
    assert session.get("/me").status_code == 401
    with owner():
        assert (
            not TOTPDevice.objects.filter(user=user).exists()
            and not MfaBackupCode.objects.filter(user=user).exists()
        )
    assert Api().post("/auth/login", {"email": user.email, "password": PASSWORD}).json() == {
        "step": "MFA_ENROLLMENT_REQUIRED"
    }


def test_admin_cannot_reset_mfa_across_organizations(admin_a: User, org_b: Organization) -> None:
    other = make_member(org_b, "SUPERVISOR", "superviseur@demo-b.rbi.test")
    with pytest.raises(User.DoesNotExist):
        services.reset_user_mfa(admin_a, context_for_user(admin_a), other.pk)


def test_non_admin_cannot_reset_mfa(org_a: Organization, enrolled: tuple[User, list[str]]) -> None:
    from apps.users.rbac import PermissionDeniedError

    agent = make_member(org_a, "AGENT", "agent.reset@demo-a.rbi.test")
    user, _ = enrolled
    with pytest.raises(PermissionDeniedError):
        services.reset_user_mfa(agent, context_for_user(agent), user.pk)
    with owner():
        assert TOTPDevice.objects.filter(user=user).exists()


def test_server_command_resets_platform_account_mfa(api: Api, platform_admin: User) -> None:
    platform_admin.set_password(PASSWORD)
    with owner():
        platform_admin.save()
    enroll(api, platform_admin)
    out = io.StringIO()
    with owner():  # commande de maintenance : rôle propriétaire (service migrate)
        call_command("reset_user_mfa", email=platform_admin.email, stdout=out)
    assert api.get("/me").status_code == 401
    with owner():
        assert not TOTPDevice.objects.filter(user=platform_admin).exists()


def test_server_mfa_reset_refused_with_application_role(platform_admin: User) -> None:
    from apps.core.maintenance import MaintenanceRoleRequired

    with pytest.raises(MaintenanceRoleRequired):
        services.server_reset_mfa(platform_admin.email)
