"""Génération OpenAPI 3 (drf-spectacular) : authentification par session et politique d'accès de chaque route.

Chaque opération porte l'extension ``x-rbi-policy`` (``public``, ``authenticated`` ou ``permission:<code>``)
et une phrase en tête de description ; les routes publiques n'exigent aucune authentification (``security:
[]``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema


class SessionCookieScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    target_class = "apps.core.api.policy.RBISessionAuthentication"
    name = "sessionCookie"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.SESSION_COOKIE_NAME,
            "description": (
                "Session ouverte par POST /auth/login (puis /auth/mfa/verify si la MFA est exigée). Cookie "
                "HttpOnly. Toute méthode non sûre exige aussi l'en-tête X-CSRFToken (cookie csrftoken, "
                "obtenu par GET /auth/csrf)."
            ),
        }


class RBIAutoSchema(AutoSchema):
    def _policy(self) -> str:
        policy = getattr(type(self.view), "policy", None)
        return str(policy(self.method)) if callable(policy) else "public"

    def get_auth(self) -> list[dict[str, Any]]:
        if self._policy() == "public":
            return []
        return super().get_auth()

    def get_description(self) -> str:  # type: ignore[override]  # signature de drf-spectacular
        policy = self._policy()
        if policy == "public":
            prefix = "Accès : public."
        elif policy == "authenticated":
            prefix = "Accès : tout compte authentifié (session complète), pour ses propres données."
        else:
            prefix = f"Accès : permission RBAC `{policy.split(':', 1)[1]}`, évaluée dans le contexte serveur."
        description = super().get_description() or ""
        return f"{prefix}\n\n{description}".strip()

    def get_operation(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        operation = super().get_operation(*args, **kwargs)
        if operation is not None:
            operation["x-rbi-policy"] = self._policy()
        return operation
