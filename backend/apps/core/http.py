"""Réponses d'erreur normalisées (RFC 9457 « Problem Details ») et marquage des routes publiques."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import JsonResponse


def problem(
    status: int,
    title: str,
    detail: str | None = None,
    errors: dict[str, list[str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JsonResponse:
    """Erreur au format ``application/problem+json``. Ne jamais y placer de secret ni d'information
    interne."""
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    response = JsonResponse(body, status=status, content_type="application/problem+json")
    response["Cache-Control"] = "no-store"
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def public_endpoint[F: Callable[..., Any]](view: F) -> F:
    """Rend une vue accessible sans authentification. Toute autre vue de l'API exige une session complète
    (MFA comprise) : refus par défaut, voir apps.authentication.middleware."""
    view.rbi_public = True  # type: ignore[attr-defined]
    return view


def csrf_failure(request: Any, reason: str = "") -> JsonResponse:
    """Refus CSRF au format de l'API (la page HTML de Django détaillerait la cause en mode DEBUG)."""
    return problem(403, "Requête refusée", "Jeton de sécurité manquant ou invalide. Rechargez la page.")


# --- Gestionnaires d'erreurs Django (hors vues DRF) et taille des requêtes (P2.8) -------------------------


def bad_request(request: Any, exception: Exception | None = None) -> JsonResponse:
    return problem(400, "Requête invalide")


def permission_denied(request: Any, exception: Exception | None = None) -> JsonResponse:
    return problem(403, "Vous n'avez pas accès à cette ressource")


def not_found(request: Any, exception: Exception | None = None) -> JsonResponse:
    return problem(404, "Ressource introuvable")


def server_error(request: Any) -> JsonResponse:
    """Exception inattendue : aucun détail technique dans la réponse (trace dans les journaux du serveur ;
    l'en-tête X-Request-ID permet de la retrouver)."""
    return problem(500, "Erreur interne", "Une erreur inattendue s'est produite.")


class RequestSizeLimitMiddleware:
    """Refuse (413) un corps annoncé plus grand que ``RBI_API_MAX_BODY_BYTES`` avant toute lecture ; un corps
    sans Content-Length est borné à la lecture par le parseur JSON de l'API."""

    def __init__(self, get_response: Callable[[Any], Any]) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        from django.conf import settings

        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return problem(400, "Requête invalide")
        if length > int(settings.RBI_API_MAX_BODY_BYTES):
            return problem(413, "Requête trop volumineuse")
        return self.get_response(request)


ERROR_TITLES = {
    400: "Requête invalide",
    403: "Vous n'avez pas accès à cette ressource",
    404: "Ressource introuvable",
    405: "Méthode non autorisée",
    413: "Requête trop volumineuse",
}
# Réponse JSON d'une API : aucune ressource à charger, jamais affichée dans un cadre (OWASP REST Security).
API_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}
KEPT_HEADERS = ("Allow", "Retry-After")


class ApiResponseMiddleware:
    """Forme des réponses sous ``/api/`` (P2.8).

    - Toute erreur (≥ 400) qui n'est pas déjà du JSON devient une réponse RFC 9457 générique, y compris en
      développement (``DEBUG``) : Django y renverrait sinon sa page technique — liste des routes (404), ou
      trace, paramètres et URL Redis avec mot de passe (500). La trace reste dans les
      journaux du serveur (``django.request``), retrouvable par l'en-tête ``X-Request-ID``.
    - En-têtes de sécurité d'une API JSON (``API_SECURITY_HEADERS``).
    """

    def __init__(self, get_response: Callable[[Any], Any]) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        response = self.get_response(request)
        if not request.path.startswith("/api/"):
            return response
        status = response.status_code
        if status >= 400 and "json" not in response.get("Content-Type", ""):
            replacement = (
                server_error(request)
                if status >= 500
                else problem(status, ERROR_TITLES.get(status, "Requête refusée"))
            )
            for name in KEPT_HEADERS:
                if response.has_header(name):
                    replacement[name] = response[name]
            response = replacement
        for name, value in API_SECURITY_HEADERS.items():
            response.setdefault(name, value)
        return response
