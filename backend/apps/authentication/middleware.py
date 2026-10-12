"""Middlewares de session et de refus par défaut.

``SessionPolicyMiddleware`` (après AuthenticationMiddleware) : une session authentifiée n'est conservée que si
- elle a été ouverte par le parcours RBI (horodatage présent) et n'a pas dépassé la durée absolue (12 h) ;
  l'inactivité (30 min) est gérée par l'expiration glissante du cookie et du cache de session ;
- la MFA a été vérifiée dans cette session si elle est exigée MAINTENANT (rôle promu ou MFA activée ailleurs).
Le compte désactivé, l'organisme non ACTIVE et l'empreinte de sécurité renouvelée sont déjà traités par
``RBIAuthBackend.get_user`` et ``User.get_session_auth_hash``.

``AuthenticationRequiredMiddleware`` : toute vue exige une session complète, sauf celles marquées
``@public_endpoint`` (refus par défaut, réponse 401 RFC 9457).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse

from apps.audit.services import record_event
from apps.core.http import problem

from . import mfa
from .services import AUTH_AT_KEY, MFA_VERIFIED_KEY


class SessionPolicyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            reason = self._violation(request)
            if reason:
                record_event(
                    "auth.session.terminate",
                    outcome="success",
                    actor_id=user.pk,
                    organization_id=getattr(user, "organization_id", None),
                    details={"reason": reason},
                )
                logout(request)
        return self.get_response(request)

    @staticmethod
    def _violation(request: HttpRequest) -> str | None:
        opened_at = request.session.get(AUTH_AT_KEY)
        if opened_at is None:
            return "unknown_origin"
        if time.time() - float(opened_at) > settings.RBI_SESSION_ABSOLUTE_MAX:
            return "absolute_timeout"
        if not request.session.get(MFA_VERIFIED_KEY) and mfa.mfa_needed(request.user):  # type: ignore[arg-type]
            return "mfa_now_required"
        return None


class AuthenticationRequiredMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self, request: HttpRequest, view_func: Callable[..., Any], view_args: Any, view_kwargs: Any
    ) -> HttpResponse | None:
        if getattr(view_func, "rbi_public", False):
            return None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return problem(401, "Authentification requise")
        return None
