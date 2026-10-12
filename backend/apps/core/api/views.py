"""Vue de base de l'API REST v1 (P2.8, ADR 0010) : politique d'accès déclarée, refus par défaut.

Chaque vue de l'API déclare EXACTEMENT UNE politique, vérifiée dès la définition de la classe :

- ``public = True`` : route publique (liste fermée, testée) ;
- ``authenticated = True`` : tout compte authentifié (session complète, MFA comprise), pour ses PROPRES
  données (profil, mot de passe, facteurs) ;
- ``permission = "<code>"`` : permission RBAC du catalogue (P2.4), évaluée côté serveur dans le contexte
  d'organisme déterminé par le serveur (P2.3) — jamais d'après une valeur du client.

Une vue sans politique, ou avec un code inconnu, empêche le démarrage (``ImproperlyConfigured``). Un test
parcourt en outre toutes les routes (``apps/core/tests/test_api_routes.py``).

Sécurité conservée (P2.5) : DRF exempte ses vues du CSRF et ne le revérifie que pour une session
authentifiée ; ici l'exemption est RETIRÉE, le middleware CSRF de Django s'applique donc à toute requête non
sûre, publique comprise. Authentification par session uniquement. Toutes les réponses portent
``Cache-Control: no-store``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, ClassVar

from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import NotAuthenticated, ParseError
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.catalog import PERMISSIONS_BY_CODE
from apps.users.models import User

from .policy import BoundedJSONParser, RBIPolicy, RBISessionAuthentication, RequestTooLarge

HANDLERS = ("get", "post", "put", "patch", "delete")


def by_method(**codes: str) -> Mapping[str, str]:
    """Permission par méthode HTTP, table immuable : ``permission = by_method(GET="users.view", …)``."""
    return MappingProxyType({method.upper(): code for method, code in codes.items()})


class RBIPolicyMixin:
    """Politique déclarative commune à toutes les vues DRF de RBI (y compris la vue du schéma OpenAPI).

    ``permission`` : un code (toutes les méthodes) ou une table ``{"GET": code, "POST": code, …}`` couvrant
    exactement les méthodes implémentées par la vue.
    """

    public: ClassVar[bool] = False
    authenticated: ClassVar[bool] = False
    permission: ClassVar[str | Mapping[str, str] | None] = None
    abstract: ClassVar[bool] = True
    # OPTIONS exposerait la description des sérialiseurs : retiré (405).
    http_method_names: Sequence[str] = ("get", "post", "put", "patch", "delete", "head")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("abstract", False):
            return
        name = cls.__qualname__
        declared = [cls.public, cls.authenticated, cls.permission is not None]
        if sum(declared) != 1:
            raise ImproperlyConfigured(
                f"{name} : déclarer exactement une politique (public, authenticated ou permission)."
            )
        if cls.permission is None:
            return
        implemented = {m.upper() for m in HANDLERS if callable(getattr(cls, m, None))}
        table = (
            cls.permission
            if isinstance(cls.permission, Mapping)
            else dict.fromkeys(implemented, cls.permission)
        )
        if set(table) != implemented:
            raise ImproperlyConfigured(
                f"{name} : permissions {sorted(table)} ≠ méthodes {sorted(implemented)}."
            )
        unknown = [code for code in table.values() if code not in PERMISSIONS_BY_CODE]
        if unknown:
            raise ImproperlyConfigured(f"{name} : permission(s) inconnue(s) {unknown}.")

    @classmethod
    def permission_for(cls, method: str) -> str | None:
        method = "GET" if method.upper() == "HEAD" else method.upper()
        if isinstance(cls.permission, Mapping):
            return cls.permission.get(method)
        return cls.permission

    @classmethod
    def policy(cls, method: str | None = None) -> str:
        if cls.public:
            return "public"
        if cls.authenticated:
            return "authenticated"
        if method is not None:
            return f"permission:{cls.permission_for(method)}"
        if isinstance(cls.permission, Mapping):
            return "permission:" + ",".join(f"{m}={c}" for m, c in sorted(cls.permission.items()))
        return f"permission:{cls.permission}"

    @classmethod
    def as_view(cls, **initkwargs: Any) -> Any:
        view = super().as_view(**initkwargs)  # type: ignore[misc]
        view.csrf_exempt = False  # le middleware CSRF s'applique (ADR 0007) : aucune exemption
        view.rbi_public = cls.public  # lu par AuthenticationRequiredMiddleware (refus par défaut, P2.5)
        view.rbi_policy = cls.policy()
        return view

    def finalize_response(self, request: Any, response: Any, *args: Any, **kwargs: Any) -> Any:
        response = super().finalize_response(request, response, *args, **kwargs)  # type: ignore[misc]
        response["Cache-Control"] = "no-store"
        return response


class RBIAPIView(RBIPolicyMixin, APIView):
    """Base de toute vue de l'API v1."""

    abstract = True
    authentication_classes = (RBISessionAuthentication,)
    permission_classes = (RBIPolicy,)
    parser_classes = (BoundedJSONParser,)
    renderer_classes: tuple[type[BaseRenderer], ...] = (JSONRenderer,)

    # Parcours d'authentification (P2.5) : un corps illisible est traité comme vide, pour que tous les échecs
    # restent indiscernables (même réponse qu'un mauvais mot de passe). Un corps trop volumineux reste refusé.
    lenient_body: ClassVar[bool] = False

    def actor(self, request: Request) -> User:
        """Compte authentifié de la requête (garanti par la politique ; refus 401 sinon)."""
        user = request.user
        if not isinstance(user, User):
            raise NotAuthenticated
        return user

    def json_body(self, request: Request) -> dict[str, Any]:
        """Corps JSON objet (vide si absent) ; un tableau ou un scalaire est refusé (400)."""
        try:
            data = request.data
        except RequestTooLarge:
            raise
        except ParseError:
            if self.lenient_body:
                return {}
            raise
        if self.lenient_body and not isinstance(data, dict):
            return {}
        if data is None or data == {}:
            return {}
        if not isinstance(data, dict):
            raise ParseError("Un objet JSON est attendu.")
        return data


def no_content() -> Response:
    return Response(status=204)
