from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.core.http import public_endpoint

from .services import run_readiness_checks


@public_endpoint
@never_cache
@require_GET
def live(request: HttpRequest) -> JsonResponse:
    """Le processus répond : aucune dépendance interrogée."""
    return JsonResponse({"status": "ok"})


@public_endpoint
@never_cache
@require_GET
def ready(request: HttpRequest) -> JsonResponse:
    """Le service peut traiter des requêtes : base de données et Redis joignables."""
    checks = run_readiness_checks()
    healthy = all(checks.values())
    return JsonResponse(
        {
            "status": "ok" if healthy else "unavailable",
            "checks": {k: "ok" if v else "error" for k, v in checks.items()},
        },
        status=200 if healthy else 503,
    )
