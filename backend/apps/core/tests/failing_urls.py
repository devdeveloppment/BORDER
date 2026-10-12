"""Routes de test uniquement : exceptions inattendues (vue DRF et vue Django) pour vérifier la réponse 500."""

from typing import Any

from django.urls import path
from rest_framework.response import Response

from apps.core.api.views import RBIAPIView
from apps.core.http import public_endpoint


class Explodes(RBIAPIView):
    public = True

    def get(self, request: Any) -> Response:
        raise RuntimeError("détail interne : mot de passe de la base = Fictif-Secret-Interne")


@public_endpoint
def explodes_plain(request: Any) -> Any:
    raise RuntimeError("détail interne : chemin /opt/venv/lib/python3.13")


urlpatterns = [
    path("api/v1/explodes", Explodes.as_view()),
    path("api/v1/explodes-plain", explodes_plain),
]

handler500 = "apps.core.http.server_error"
handler404 = "apps.core.http.not_found"
