"""Schéma OpenAPI servi par l'application : réservé aux comptes authentifiés (§15.1).

Aucune interface Swagger UI ni ReDoc n'est servie : elles chargeraient du JavaScript depuis un CDN externe
(drf-spectacular-sidecar non retenu). Le schéma de référence est versionné : ``openapi/rbi-api-v1.yaml``.
"""

from __future__ import annotations

from drf_spectacular.views import SpectacularAPIView

from .policy import RBIPolicy, RBISessionAuthentication
from .views import RBIPolicyMixin


class SchemaView(RBIPolicyMixin, SpectacularAPIView):
    authenticated = True
    authentication_classes = (RBISessionAuthentication,)
    permission_classes = (RBIPolicy,)
