"""Utilitaires des tests d'authentification : client HTTP avec CSRF RÉELLEMENT appliqué, comptes fictifs,
codes TOTP."""

from __future__ import annotations

import json
import time
from typing import Any

from django.test import Client
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.organizations.models import Organization
from apps.users.models import User
from conftest import grant_role, owner

PASSWORD = "Fictif-Auth-2026-mdp!"  # mot de passe de test (fictif)


class Api:
    """Client navigateur : cookie de session, jeton CSRF relu dans le cookie ``csrftoken`` (comme le
    frontend)."""

    def __init__(self) -> None:
        self.client = Client(enforce_csrf_checks=True)

    def csrf(self) -> str:
        response = self.client.get("/api/v1/auth/csrf")
        assert response.status_code == 204
        return str(self.client.cookies["csrftoken"].value)

    def post(self, path: str, data: dict[str, Any] | None = None, *, csrf: bool = True, **extra: Any) -> Any:
        headers = dict(extra.pop("headers", {}))
        if csrf:
            token = self.client.cookies.get("csrftoken")
            headers["X-CSRFToken"] = token.value if token else self.csrf()
        return self.client.post(
            f"/api/v1{path}",
            data=json.dumps(data or {}),
            content_type="application/json",
            headers=headers,
            **extra,
        )

    def get(self, path: str, **extra: Any) -> Any:
        return self.client.get(f"/api/v1{path}", **extra)

    @property
    def session_key(self) -> str | None:
        cookie = self.client.cookies.get("rbi_session")
        return cookie.value if cookie else None


def make_member(org: Organization | None, role: str | None, email: str, *, password: str = PASSWORD) -> User:
    with owner():
        user = User.objects.create_user(email=email, password=password, organization=org)
    if role:
        grant_role(user, role)
    return user


def totp_code(device: TOTPDevice, steps: int = 0) -> str:
    """Code TOTP de l'appareil, décalé de ``steps`` pas de 30 s (négatif : code ancien)."""
    otp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    otp.time = time.time() + steps * device.step
    return str(otp.token()).zfill(device.digits)


def enroll(api: Api, user: User, password: str = PASSWORD) -> list[str]:
    """Première connexion d'un rôle à MFA obligatoire : enrôlement complet. Renvoie les codes de secours."""
    assert api.post("/auth/login", {"email": user.email, "password": password}).json() == {
        "step": "MFA_ENROLLMENT_REQUIRED"
    }
    assert api.post("/auth/mfa/enroll").status_code == 200
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=False)
    response = api.post("/auth/mfa/verify", {"code": totp_code(device)})
    assert response.status_code == 200, response.content
    return list(response.json()["backup_codes"])


def login_with_mfa(api: Api, user: User, *, steps: int = 1, password: str = PASSWORD) -> None:
    """Connexion d'un compte déjà enrôlé (code du pas suivant : jamais un code déjà utilisé)."""
    assert api.post("/auth/login", {"email": user.email, "password": password}).json() == {
        "step": "MFA_REQUIRED"
    }
    with owner():
        device = TOTPDevice.objects.get(user=user, confirmed=True)
    response = api.post("/auth/mfa/verify", {"code": totp_code(device, steps)})
    assert response.status_code == 200, response.content
