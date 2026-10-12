"""API du journal d'audit (écran 22, §9.11 « recherche et filtres ; export pour l'auditeur » ; ADR 0009,
0010).

- Organisme : ``/audit-logs`` (+ ``/export``, ``/integrity``), permission ``audit.view``, entrées de SON
  organisme (contexte serveur ; aucun identifiant d'organisme accepté du client).
- Plateforme : ``/platform/audit-logs`` (+ ``/export``, ``/integrity``), permission ``platform.audit`` et
  ``PlatformScope`` délivré : entrées de portée plateforme uniquement.

Lecture seule : aucune méthode de modification ni de suppression n'existe (405). Paramètres validés ; un
paramètre inconnu est refusé (400). Pagination bornée (100 par page, 10 000 premiers résultats) ; export CSV
limité à 10 000 lignes, refusé au-delà. Chaque consultation, export et vérification est journalisé (P2.7).
Les entrées ne contiennent aucun secret (P2.7 : validation à l'écriture) ; les acteurs sont présentés par leur
adresse lorsqu'elle est lisible dans le périmètre (RLS), sinon par un libellé neutre.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
from typing import Any

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.errors import ProblemSerializer
from apps.core.api.pagination import Page, page_from, paginated_serializer
from apps.core.api.throttling import ScopedRateThrottle, UserRateThrottle
from apps.core.api.views import RBIAPIView
from apps.organizations.platform import platform_scope
from apps.organizations.tenancy import get_current_tenant

from . import selectors
from .catalog import OBJECT_TYPES
from .integrity import ChainReport
from .models import AuditLog
from .selectors import PLATFORM_AUDIT, AuditQuery, AuditResult, ExportMentionError, ExportTooLarge

ORG_TAG = "Journal d'audit — organisme"
PLATFORM_TAG = "Journal d'audit — plateforme"
PROBLEM = OpenApiResponse(ProblemSerializer, description="Erreur (RFC 9457)")
FILTERS = ("date_from", "date_to", "action", "outcome", "actor_id", "object_type", "object_id", "ordering")
PAGE_PARAMS = ("page", "page_size")
RESULT_FR = {"success": "succes", "denied": "echec", "failure": "echec"}
ACTOR_FALLBACK = {"system": "Système", "anonymous": "Anonyme"}


class FlexibleDateTimeField(serializers.DateTimeField):
    """Date-heure ISO 8601 ou date seule (début de journée UTC)."""

    def to_internal_value(self, value: Any) -> datetime.datetime:
        if isinstance(value, str) and len(value) == 10:
            try:
                day = datetime.date.fromisoformat(value)
            except ValueError:
                self.fail("invalid", format="AAAA-MM-JJ ou ISO 8601")
            return datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.UTC)
        return super().to_internal_value(value)


class AuditQuerySerializer(serializers.Serializer[Any]):
    date_from = FlexibleDateTimeField(required=False, help_text="Inclus (ISO 8601 ou AAAA-MM-JJ, UTC).")
    date_to = FlexibleDateTimeField(required=False, help_text="Exclu (ISO 8601 ou AAAA-MM-JJ, UTC).")
    action = serializers.RegexField(
        r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$",
        max_length=64,
        required=False,
        help_text="Catégorie (« auth », « auth.mfa ») ou action exacte.",
    )
    outcome = serializers.ChoiceField(choices=[c for c, _ in AuditLog.Outcome.choices], required=False)
    actor_id = serializers.UUIDField(required=False)
    object_type = serializers.ChoiceField(choices=sorted(OBJECT_TYPES), required=False)
    object_id = serializers.RegexField(r"^[A-Za-z0-9_.:-]{1,64}$", required=False)
    ordering = serializers.ChoiceField(choices=["-id", "id"], default="-id")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("date_from") and attrs.get("date_to") and attrs["date_from"] >= attrs["date_to"]:
            raise serializers.ValidationError({"date_to": ["Doit être postérieure à date_from."]})
        return attrs


def _query(request: Request, allowed: tuple[str, ...]) -> AuditQuery:
    unknown = sorted(set(request.query_params) - set(allowed))
    if unknown:
        raise ValidationError({name: ["Paramètre non pris en charge."] for name in unknown})
    serializer = AuditQuerySerializer(
        data={k: request.query_params[k] for k in FILTERS if k in request.query_params}
    )
    serializer.is_valid(raise_exception=True)
    return AuditQuery(**serializer.validated_data)


class AuditEntrySerializer(serializers.Serializer[Any]):
    """Contrat P1 ``AuditEntry`` + champs exacts du journal (``outcome``, ``actor_type``, ``actor_id``, …)."""

    id = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    scope = serializers.ChoiceField(choices=AuditLog.Scope.choices)
    organization_id = serializers.UUIDField(allow_null=True)
    actor = serializers.CharField(help_text="Adresse si lisible dans le périmètre, sinon libellé neutre.")
    actor_type = serializers.ChoiceField(choices=AuditLog.ActorType.choices)
    actor_id = serializers.UUIDField(allow_null=True)
    action = serializers.CharField()
    outcome = serializers.ChoiceField(choices=AuditLog.Outcome.choices)
    result = serializers.ChoiceField(
        choices=["succes", "echec"], help_text="Contrat P1 : refus et échecs → echec."
    )
    object_type = serializers.CharField(help_text="Vide si l'événement ne vise pas d'objet.")
    object_id = serializers.CharField(allow_null=True)
    object_repr = serializers.CharField()
    ip_address = serializers.CharField(allow_null=True)
    request_id = serializers.UUIDField(allow_null=True)
    old_value = serializers.DictField(allow_null=True)
    new_value = serializers.DictField(allow_null=True)
    details = serializers.DictField()
    prev_hash = serializers.CharField()
    hash = serializers.CharField()


class AuditPageSerializer(paginated_serializer("AuditPageBase", AuditEntrySerializer)):  # type: ignore[misc]
    chain_integrity = serializers.ChoiceField(
        choices=["valide", "rompue", "non_verifiee"],
        help_text="Toujours « non_verifiee » ici : la vérification complète passe par …/integrity.",
    )


class IntegritySerializer(serializers.Serializer[Any]):
    chain = serializers.CharField()
    chain_integrity = serializers.ChoiceField(choices=["valide", "rompue"])
    checked = serializers.IntegerField()
    head_hash = serializers.CharField(help_text="Empreinte de tête : à conserver hors de la base (ancrage).")
    errors = serializers.ListField(child=serializers.CharField())  # type: ignore[assignment]  # cf. ProblemSerializer
    verified_at = serializers.DateTimeField()


def _iso(value: datetime.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _actor(row: AuditLog, labels: dict[Any, str]) -> str:
    if row.actor_id and row.actor_id in labels:
        return labels[row.actor_id]
    if row.actor_type in ACTOR_FALLBACK:
        return ACTOR_FALLBACK[row.actor_type]
    return f"Compte {str(row.actor_id)[:8]}"


def _entry(row: AuditLog, labels: dict[Any, str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": _iso(row.created_at),
        "scope": row.scope,
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "actor": _actor(row, labels),
        "actor_type": row.actor_type,
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "action": row.action,
        "outcome": row.outcome,
        "result": RESULT_FR[row.outcome],
        "object_type": row.object_type or "",
        "object_id": row.object_id,
        "object_repr": f"{row.object_type}:{row.object_id}" if row.object_id else (row.object_type or ""),
        "ip_address": row.ip_address,
        "request_id": str(row.request_id) if row.request_id else None,
        "old_value": row.old_value,
        "new_value": row.new_value,
        "details": row.metadata,
        "prev_hash": row.prev_hash,
        "hash": row.hash,
    }


def _page_body(result: AuditResult, page: Page) -> dict[str, Any]:
    body = page.body(result.count, [_entry(row, result.actors) for row in result.rows])
    body["chain_integrity"] = "non_verifiee"
    return body


def _integrity(report: ChainReport) -> dict[str, Any]:
    return {
        "chain": report.chain,
        "chain_integrity": "valide" if report.intact else "rompue",
        "checked": report.checked,
        "head_hash": report.head_hash,
        "errors": list(report.errors[:20]),
        "verified_at": _iso(timezone.now()),
    }


# --- Export CSV ---------------------------------------------------------------------------------------

CSV_COLUMNS = (
    "id",
    "created_at",
    "scope",
    "organization_id",
    "actor",
    "actor_type",
    "actor_id",
    "action",
    "outcome",
    "object_type",
    "object_id",
    "ip_address",
    "request_id",
    "old_value",
    "new_value",
    "details",
    "prev_hash",
    "hash",
)


# Première colonne de chaque export : identifie les données de démonstration sans rendre le CSV invalide.
DEMO_MENTION = "DONNÉES DE DÉMONSTRATION"
UNDETERMINED_MENTION = "STATUT INDÉTERMINÉ"  # journal plateforme : organisme visé, statut non établi
MENTIONS = {"demo": DEMO_MENTION, "undetermined": UNDETERMINED_MENTION, None: None}


class ExportRefused(APIException):
    """Mention de démonstration impossible à établir : refus explicite, jamais une cellule vide."""

    status_code = 500
    default_detail = "Export impossible : la mention de démonstration n'a pas pu être établie."


def _cell(value: Any) -> str:
    """Valeur CSV ; neutralise l'injection de formules dans un tableur (=, +, -, @, tabulation, retour)."""
    if value is None:
        return ""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv_response(result: AuditResult, name: str) -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("mention", *CSV_COLUMNS))
    organization_mention = _cell(DEMO_MENTION if result.demo else None)
    for row in result.rows:
        entry = _entry(row, result.actors)
        # Journal plateforme : mention par entrée ; une entrée sans statut calculé lève une erreur (KeyError).
        mention = (
            organization_mention if result.statuses is None else _cell(MENTIONS[result.statuses[row.id]])
        )
        writer.writerow([mention, *(_cell(entry[column]) for column in CSV_COLUMNS)])
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    response = HttpResponse(buffer.getvalue().encode("utf-8"), content_type="text/csv; charset=utf-8")
    suffix = "-demonstration" if result.demo else ""
    response["Content-Disposition"] = f'attachment; filename="rbi-audit-{name}{suffix}-{stamp}.csv"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


class CSVRenderer(BaseRenderer):
    """Permet la négociation ``Accept: text/csv`` ; les erreurs restent du JSON (RFC 9457)."""

    media_type = "text/csv"
    format = "csv"
    charset = "utf-8"

    def render(self, data: Any, accepted_media_type: Any = None, renderer_context: Any = None) -> bytes:
        return data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()


def _too_large(exc: ExportTooLarge) -> ValidationError:
    return ValidationError(
        {
            "non_field_errors": [
                f"{exc.count} entrées : l'export est limité à {selectors.EXPORT_MAX_ROWS} lignes. "
                "Affiner la période ou les filtres."
            ]
        }
    )


QUERY_PARAMETERS = [
    OpenApiParameter(
        "date_from", OpenApiTypes.DATETIME, description="Début inclus (ISO 8601 ou AAAA-MM-JJ)."
    ),
    OpenApiParameter("date_to", OpenApiTypes.DATETIME, description="Fin exclue (ISO 8601 ou AAAA-MM-JJ)."),
    OpenApiParameter("action", OpenApiTypes.STR, description="Catégorie (« auth ») ou action exacte."),
    OpenApiParameter("outcome", OpenApiTypes.STR, enum=["success", "denied", "failure"]),
    OpenApiParameter("actor_id", OpenApiTypes.UUID),
    OpenApiParameter("object_type", OpenApiTypes.STR, enum=sorted(OBJECT_TYPES)),
    OpenApiParameter("object_id", OpenApiTypes.STR),
    OpenApiParameter(
        "ordering", OpenApiTypes.STR, enum=["-id", "id"], description="Défaut : -id (récent d'abord)."
    ),
]
PAGE_PARAMETERS = [
    OpenApiParameter("page", OpenApiTypes.INT, description="≥ 1 (défaut 1)."),
    OpenApiParameter(
        "page_size", OpenApiTypes.INT, description="1 à 100 (défaut 50) ; page * page_size ≤ 10 000."
    ),
]
CSV_RESPONSE = OpenApiResponse(
    OpenApiTypes.STR,
    description="Fichier CSV (UTF-8), 10 000 lignes au plus. Première colonne « mention » : "
    "« DONNÉES DE DÉMONSTRATION » pour un organisme de démonstration, vide sinon ; journal plateforme : "
    "statut enregistré dans l'entrée, « STATUT INDÉTERMINÉ » si un organisme est visé sans statut établi.",
)


# --- Organisme ----------------------------------------------------------------------------------------


class HeavyAuditView(RBIAPIView):
    """Opération coûteuse (proportionnelle au journal) : au plus 10 requêtes par minute et par compte,
    réponse 429 au-delà."""

    # Taux dédié ``audit_heavy`` en plus du taux général.

    abstract = True
    throttle_classes = (ScopedRateThrottle, UserRateThrottle)
    throttle_scope = "audit_heavy"


class OrganizationAuditView(RBIAPIView):
    permission = "audit.view"

    @extend_schema(
        tags=[ORG_TAG],
        summary="Consulter le journal de son organisme",
        parameters=PAGE_PARAMETERS + QUERY_PARAMETERS,
        responses={200: AuditPageSerializer, 400: PROBLEM, 403: PROBLEM},
    )
    def get(self, request: Request) -> Response:
        query, page = _query(request, FILTERS + PAGE_PARAMS), page_from(request.query_params)
        result = selectors.organization_page(
            self.actor(request), get_current_tenant(), query, offset=page.offset, limit=page.page_size
        )
        return Response(_page_body(result, page))


class OrganizationAuditExportView(HeavyAuditView):
    permission = "audit.view"
    renderer_classes = (JSONRenderer, CSVRenderer)

    @extend_schema(
        tags=[ORG_TAG],
        summary="Exporter le journal de son organisme (CSV)",
        parameters=QUERY_PARAMETERS,
        responses={(200, "text/csv"): CSV_RESPONSE, 400: PROBLEM, 403: PROBLEM},
    )
    def get(self, request: Request) -> HttpResponse:
        query = _query(request, FILTERS)
        try:
            result = selectors.organization_export(self.actor(request), get_current_tenant(), query)
        except ExportTooLarge as exc:
            raise _too_large(exc) from exc
        return _csv_response(result, "organisme")


class OrganizationAuditIntegrityView(HeavyAuditView):
    permission = "audit.view"

    @extend_schema(
        tags=[ORG_TAG],
        summary="Vérifier l'intégrité de la chaîne de son organisme",
        responses={200: IntegritySerializer, 403: PROBLEM},
    )
    def get(self, request: Request) -> Response:
        _query(request, ())
        return Response(
            _integrity(selectors.verify_organization_chain(self.actor(request), get_current_tenant()))
        )


# --- Plateforme ---------------------------------------------------------------------------------------


def _platform_scope(request: Request, purpose: str) -> Any:
    return platform_scope(request.user, purpose=purpose, permission=PLATFORM_AUDIT)


class PlatformAuditView(RBIAPIView):
    permission = PLATFORM_AUDIT

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Consulter le journal de la plateforme",
        parameters=PAGE_PARAMETERS + QUERY_PARAMETERS,
        responses={200: AuditPageSerializer, 400: PROBLEM, 403: PROBLEM},
    )
    def get(self, request: Request) -> Response:
        query, page = _query(request, FILTERS + PAGE_PARAMS), page_from(request.query_params)
        scope = _platform_scope(request, "consultation du journal plateforme")
        return Response(
            _page_body(selectors.platform_page(scope, query, offset=page.offset, limit=page.page_size), page)
        )


class PlatformAuditExportView(HeavyAuditView):
    permission = PLATFORM_AUDIT
    renderer_classes = (JSONRenderer, CSVRenderer)

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Exporter le journal de la plateforme (CSV)",
        parameters=QUERY_PARAMETERS,
        responses={(200, "text/csv"): CSV_RESPONSE, 400: PROBLEM, 403: PROBLEM},
    )
    def get(self, request: Request) -> HttpResponse:
        query = _query(request, FILTERS)
        scope = _platform_scope(request, "export du journal plateforme")
        try:
            result = selectors.platform_export(scope, query)
        except ExportTooLarge as exc:
            raise _too_large(exc) from exc
        except ExportMentionError as exc:
            raise ExportRefused from exc
        return _csv_response(result, "plateforme")


class PlatformAuditIntegrityView(HeavyAuditView):
    permission = PLATFORM_AUDIT

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Vérifier l'intégrité de la chaîne plateforme",
        responses={200: IntegritySerializer, 403: PROBLEM},
    )
    def get(self, request: Request) -> Response:
        _query(request, ())
        scope = _platform_scope(request, "vérification de la chaîne plateforme")
        return Response(_integrity(selectors.verify_platform_chain(scope)))
