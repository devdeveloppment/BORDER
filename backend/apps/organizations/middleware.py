"""Pose le périmètre de chaque requête authentifiée, applicatif ET PostgreSQL (P2.3, P2.6).

- Source unique : ``request.user``, reconstruit depuis la base à chaque requête (backend RBI). Aucun en-tête,
  paramètre d'URL ni champ de corps n'est lu : un ``organization_id`` fourni par le client n'a aucun effet.
- Utilisateur organisationnel : ``tenant_context`` (organisme + compte) pour toute la requête, qui s'exécute
  donc dans une transaction ; organisme non ACTIVE : 403 générique.
- Compte plateforme : périmètre limité à son propre compte, sans organisme ; les opérations globales ajoutent
  ``app.platform`` uniquement pendant un ``PlatformScope`` délivré.
- Requête anonyme : aucun périmètre ; les politiques RLS ne laissent alors rien passer.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.audit.services import record_event
from apps.core.db_scope import identity_scope
from apps.core.http import problem

from .exceptions import TenantAccessDenied
from .tenancy import context_for_user, tenant_context


class TenantContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return self.get_response(request)
        if getattr(user, "organization_id", None) is None:
            with identity_scope(user.pk):
                return self.get_response(request)
        try:
            context = context_for_user(user)
        except TenantAccessDenied:
            record_event(
                "tenant.access",
                outcome="denied",
                actor_id=user.pk,
                organization_id=user.organization_id,
                details={"reason": "organization_not_active"},
            )
            # Même forme que tout refus de l'API (RFC 9457, no-store).
            return problem(403, "Vous n'avez pas accès à cette ressource")
        with tenant_context(context):
            return self.get_response(request)
