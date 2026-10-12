"""Erreurs de l'API au format RFC 9457 (Problem Details), sans aucun détail interne (P2.8, ADR 0010).

| Cas | Statut | Titre |
|---|---|---|
| corps ou paramètres invalides | 400 | « Requête invalide » (+ ``errors`` par champ) |
| non authentifié | 401 | « Authentification requise » |
| permission, contexte d'organisme ou périmètre plateforme refusé | 403 | « Vous n'avez pas accès à cette
ressource » | | objet inexistant OU d'un autre organisme (indiscernables, §15.1) | 404 | « Ressource
introuvable » | | méthode non permise | 405 | « Méthode non autorisée » |
| transition métier impossible dans l'état actuel | 409 | « Opération impossible » (+ message métier) |
| corps trop volumineux | 413 | « Requête trop volumineuse » |
| type de contenu non JSON | 415 | « Type de contenu non pris en charge » |
| trop de requêtes | 429 | « Trop de tentatives » (+ ``Retry-After``) |
| toute autre exception | 500 | « Erreur interne » (vue ``server_error`` ; détail uniquement dans les
journaux) |

Les messages des refus ne nomment jamais la permission manquante ni la ressource.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, serializers
from rest_framework.response import Response

FORBIDDEN = "Vous n'avez pas accès à cette ressource"
NOT_FOUND = "Ressource introuvable"


def problem_body(status: int, title: str, detail: str | None = None, errors: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return body


def _problem(
    status: int, title: str, detail: str | None = None, errors: Any = None, **headers: str
) -> Response:
    response = Response(problem_body(status, title, detail, errors), status=status)
    response.content_type = "application/problem+json"
    for name, value in headers.items():
        response[name.replace("_", "-")] = value
    return response


def _field_errors(detail: Any, prefix: str = "") -> dict[str, list[str]]:
    """Aplatit les erreurs DRF : {"champ": ["message", …]} (sous-champs : « parent.enfant »)."""
    errors: dict[str, list[str]] = {}
    if isinstance(detail, dict):
        for key, value in detail.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            for sub_key, messages in _field_errors(value, name).items():
                errors.setdefault(sub_key, []).extend(messages)
    elif isinstance(detail, list):
        for item in detail:
            if isinstance(item, dict | list):
                for sub_key, messages in _field_errors(item, prefix).items():
                    errors.setdefault(sub_key, []).extend(messages)
            else:
                errors.setdefault(prefix or "non_field_errors", []).append(str(item))
    else:
        errors.setdefault(prefix or "non_field_errors", []).append(str(detail))
    return errors


def problem_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    from apps.authentication.services import AuthError
    from apps.organizations.exceptions import (
        InvalidTransition,
        PlatformAccessDenied,
        TenantAccessDenied,
        TenantContextMissing,
    )

    if isinstance(exc, AuthError):  # parcours d'authentification P2.5 : statut et titre propres
        headers = {"Retry_After": str(exc.retry_after)} if exc.retry_after else {}
        return _problem(exc.status, exc.title, exc.detail, exc.errors, **headers)
    if isinstance(exc, exceptions.NotAuthenticated | exceptions.AuthenticationFailed):
        return _problem(401, "Authentification requise")
    if isinstance(
        exc,
        PermissionDenied
        | exceptions.PermissionDenied
        | PlatformAccessDenied
        | TenantAccessDenied
        | TenantContextMissing,
    ):
        return _problem(403, FORBIDDEN)
    if isinstance(exc, Http404 | exceptions.NotFound | ObjectDoesNotExist):
        return _problem(404, NOT_FOUND)
    if isinstance(exc, exceptions.ValidationError):
        return _problem(400, "Requête invalide", errors=_field_errors(exc.detail))
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        return _problem(400, "Requête invalide", errors=_field_errors(detail))
    if isinstance(exc, InvalidTransition):
        return _problem(409, "Opération impossible", str(exc))
    if isinstance(exc, exceptions.MethodNotAllowed):
        return _problem(405, "Méthode non autorisée")
    if isinstance(exc, exceptions.UnsupportedMediaType):
        return _problem(415, "Type de contenu non pris en charge", "Envoyer du JSON (application/json).")
    if isinstance(exc, exceptions.Throttled):
        wait = int(getattr(exc, "wait", None) or 1)
        return _problem(429, "Trop de tentatives", "Veuillez réessayer plus tard.", Retry_After=str(wait))
    if isinstance(exc, exceptions.ParseError) and exc.status_code == 413:
        return _problem(413, "Requête trop volumineuse")
    if isinstance(exc, exceptions.ParseError):
        return _problem(400, "Requête invalide", "Corps de requête JSON invalide.")
    if isinstance(exc, exceptions.NotAcceptable):
        return _problem(406, "Format de réponse non disponible")
    if isinstance(exc, exceptions.APIException):  # autre erreur DRF : statut conservé, message générique
        return _problem(exc.status_code, "Requête refusée")
    return None  # exception inattendue : vue server_error (500), journalisée par Django


class ProblemSerializer(serializers.Serializer[Any]):
    """Schéma OpenAPI des erreurs (RFC 9457)."""

    type = serializers.CharField(default="about:blank")
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField(required=False)
    # Champ « errors » du contrat RFC 9457 / P1 ; DRF retire les champs déclarés des attributs de classe.
    errors = serializers.DictField(  # type: ignore[assignment]
        child=serializers.ListField(child=serializers.CharField()), required=False
    )
