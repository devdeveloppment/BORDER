"""Authentification, politique d'accès et parseur de l'API (référencés par REST_FRAMEWORK dans les réglages).

Module séparé de ``views.py`` : DRF lit ses réglages au chargement d'``APIView`` ; ces classes ne doivent donc
pas importer ``rest_framework.views`` (import circulaire).
"""

from __future__ import annotations

import io
from typing import Any

from django.conf import settings
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from apps.users.catalog import PERMISSIONS_BY_CODE


class RequestTooLarge(ParseError):
    status_code = 413
    default_detail = "Requête trop volumineuse."
    default_code = "request_too_large"


MAX_JSON_DEPTH = 16  # les corps de l'API ont au plus 3 niveaux


def _acceptable(data: Any) -> bool:
    """Profondeur bornée et aucune chaîne contenant U+0000 (parcours itératif : aucune récursion)."""
    pending: list[tuple[Any, int]] = [(data, 1)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, str):
            if "\x00" in value:
                return False
        elif isinstance(value, dict | list):
            if depth > MAX_JSON_DEPTH:
                return False
            items = [*value.keys(), *value.values()] if isinstance(value, dict) else value
            pending.extend((item, depth + 1) for item in items)
    return True


class BoundedJSONParser(JSONParser):
    """JSON uniquement, taille bornée même sans en-tête Content-Length (``RBI_API_MAX_BODY_BYTES``).

    Refusés (400) : une imbrication excessive (``RecursionError`` du décodeur, hors ``ValueError``) et toute
    chaîne contenant U+0000, que PostgreSQL refuse dans un texte. Sans ces contrôles, une valeur lue hors
    sérialiseur (parcours d'authentification) provoquait une erreur 500.
    """

    def parse(self, stream: Any, media_type: str | None = None, parser_context: Any = None) -> Any:
        limit = int(settings.RBI_API_MAX_BODY_BYTES)
        raw = stream.read(limit + 1) if stream is not None else b""
        if len(raw) > limit:
            raise RequestTooLarge
        try:
            data = super().parse(io.BytesIO(raw), media_type, parser_context)
        except RecursionError as exc:
            raise ParseError("Structure JSON trop profonde.") from exc
        if not _acceptable(data):
            raise ParseError("Contenu JSON non autorisé.")
        return data


class RBISessionAuthentication(SessionAuthentication):
    """Session Django (P2.5). ``authenticate_header`` : un anonyme reçoit 401, pas 403."""

    def authenticate_header(self, request: Request) -> str:
        return 'Session realm="api"'


class RBIPolicy(BasePermission):
    """Applique la politique déclarée par la vue. La permission RBAC est évaluée par ``require_permission``,
    qui journalise chaque refus (P2.4, P2.7)."""

    def has_permission(self, request: Request, view: Any) -> bool:
        if getattr(view, "public", False):
            return True
        user = request.user
        if user is None or not user.is_authenticated:
            return False
        if getattr(view, "authenticated", False):
            return True
        permission_for = getattr(type(view), "permission_for", None)
        code = permission_for(request.method) if callable(permission_for) else None
        if code is None:  # vue sans politique (DRF par défaut) ou méthode non couverte : refus
            return False
        from apps.organizations.tenancy import current_tenant_or_none
        from apps.users.rbac import require_permission

        definition = PERMISSIONS_BY_CODE[code]
        context = current_tenant_or_none() if definition.scope == "organization" else None
        require_permission(user, code, context)
        return True
