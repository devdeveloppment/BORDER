"""Contexte technique de la requête ou de la tâche en cours : identifiant de corrélation et adresse IP (P2.7).

- L'identifiant de requête est TOUJOURS généré côté serveur (UUID v4). Un en-tête ``X-Request-ID`` envoyé par
  le client est ignoré : il ne peut ni falsifier ni relier artificiellement des entrées du journal d'audit.
  L'identifiant est renvoyé dans la réponse (en-tête ``X-Request-ID``) pour le support.
- L'adresse IP est celle de la politique unique du proxy de confiance (``apps.core.client_ip``, P2.10),
  comme pour la limitation des tentatives et DRF. Une valeur non conforme est écartée. Son enregistrement
  dans l'audit dépend de ``RBI_AUDIT_RECORD_IP``
  (§9.11 : « si juridiquement et techniquement approprié »).
- Porté par une ``ContextVar`` : propre au thread ou à la tâche, restauré en sortie.
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.http import HttpRequest, HttpResponse

from .client_ip import client_ip

REQUEST_ID_HEADER = "X-Request-ID"


@dataclass(frozen=True, slots=True)
class RequestContext:
    request_id: uuid.UUID
    ip_address: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("rbi_request_context", default=None)


def current_request_context() -> RequestContext | None:
    return _current.get()


def _valid_ip(value: object) -> str | None:
    try:
        return str(ipaddress.ip_address(str(value)))
    except ValueError:
        return None


@contextmanager
def request_context(
    request_id: uuid.UUID | None = None, ip_address: object = None
) -> Iterator[RequestContext]:
    context = RequestContext(request_id=request_id or uuid.uuid4(), ip_address=_valid_ip(ip_address))
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


class RequestContextMiddleware:
    """Premier middleware : tout événement d'audit de la requête porte le même identifiant."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with request_context(ip_address=client_ip(request)) as context:
            response = self.get_response(request)
        response[REQUEST_ID_HEADER] = str(context.request_id)
        return response
