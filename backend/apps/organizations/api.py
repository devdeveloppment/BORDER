"""API des organismes (§9.16, écrans 5, 31 ; §15.2 « /platform/organizations ») et formulaire public.

- ``/organization`` : SON organisme (contexte serveur), ``organization.view``.
- ``/public/access-requests`` : formulaire public de demande (écran 5) ; aucun compte ni droit créé ; limité à
  5 demandes par heure et par adresse.
- ``/platform/*`` : gestion des organismes par le niveau plateforme. Chaque requête obtient un
  ``PlatformScope`` pour la permission exacte de l'opération (P2.3, audité), puis appelle les services du
  cycle de vie. Aucune donnée opérationnelle ni aucun compte d'organisme n'est exposé : uniquement des
  décomptes.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import record_event
from apps.core.api.errors import ProblemSerializer
from apps.core.api.throttling import AnonRateThrottle, ScopedRateThrottle
from apps.core.api.views import RBIAPIView
from apps.users.services import INSTITUTIONAL_ADMINS_PERMISSION, create_institutional_admin

from . import selectors, services
from .exceptions import InvalidTransition
from .models import AccessRequest, Organization, OrganizationAuthorization
from .platform import MANAGE_ORGANIZATIONS, PlatformScope, platform_scope
from .tenancy import get_current_tenant

PROBLEM = OpenApiResponse(ProblemSerializer, description="Erreur (RFC 9457)")
PUBLIC_TAG = "Public"
ORG_TAG = "Organisme"
PLATFORM_TAG = "Plateforme — organismes"


def _iso(value: datetime.datetime | datetime.date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _valid(serializer_class: type[serializers.Serializer[Any]], data: Any) -> dict[str, Any]:
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _business_errors(exc: ValueError, field: str = "non_field_errors") -> ValidationError:
    """Erreur de validation métier des services (message en français, sans détail interne)."""
    return ValidationError({field: [str(exc)]})


# --- Schémas ----------------------------------------------------------------------------------------


class AuthorizationSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    reference = serializers.CharField()
    scope = serializers.CharField()
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(allow_null=True)
    created_at = serializers.DateTimeField()


class OrganizationSerializer(serializers.Serializer[Any]):
    """Contrat P1 ``PlatformOrganization``."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    short_name = serializers.CharField()
    type = serializers.ChoiceField(choices=Organization.Type.choices)
    status = serializers.ChoiceField(choices=Organization.Status.choices)
    country_code = serializers.CharField()
    timezone = serializers.CharField()
    deployment_mode = serializers.ChoiceField(choices=Organization.DeploymentMode.choices)
    is_demo = serializers.BooleanField()
    users_count = serializers.IntegerField()
    authorization_reference = serializers.CharField(allow_null=True)
    valid_from = serializers.DateField(allow_null=True)
    valid_until = serializers.DateField(allow_null=True)
    created_at = serializers.DateTimeField()


class OrganizationDetailSerializer(OrganizationSerializer):
    retention_days = serializers.IntegerField()
    authorizations = AuthorizationSerializer(many=True)


class AccessRequestSerializer(serializers.Serializer[Any]):
    """Contrat P1 ``AccessRequest``."""

    id = serializers.UUIDField()
    organization_name = serializers.CharField()
    requester_name = serializers.CharField()
    requester_role = serializers.CharField()
    email = serializers.EmailField()
    request_type = serializers.ChoiceField(choices=AccessRequest.RequestType.choices)
    created_at = serializers.DateTimeField()


class PlatformRegistrySerializer(serializers.Serializer[Any]):
    organizations = OrganizationSerializer(many=True)
    access_requests = AccessRequestSerializer(many=True)


class PublicAccessRequestSerializer(serializers.Serializer[Any]):
    """Champs du formulaire P1 (écran 5) ; ``consent`` : booléen ou chaîne « true » (formulaire P1)."""

    organization = serializers.CharField(max_length=200)
    role = serializers.CharField(max_length=150)
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    request_type = serializers.ChoiceField(choices=AccessRequest.RequestType.choices)
    message = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    consent = serializers.CharField(max_length=5)

    def validate_consent(self, value: str) -> bool:
        if str(value).strip().lower() != "true":
            raise serializers.ValidationError("Le consentement est requis.")
        return True


class DetailSerializer(serializers.Serializer[Any]):
    detail = serializers.CharField()


class OrganizationCreateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200)
    short_name = serializers.CharField(max_length=50)
    type = serializers.ChoiceField(choices=Organization.Type.choices)
    country_code = serializers.CharField(max_length=2)
    timezone = serializers.CharField(max_length=64)
    retention_days = serializers.IntegerField(min_value=1, max_value=36500)
    deployment_mode = serializers.ChoiceField(
        choices=Organization.DeploymentMode.choices, default=Organization.DeploymentMode.MUTUALISE
    )
    is_demo = serializers.BooleanField(default=False)
    access_request_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class OrganizationUpdateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200, required=False)
    short_name = serializers.CharField(max_length=50, required=False)
    type = serializers.ChoiceField(choices=Organization.Type.choices, required=False)
    country_code = serializers.CharField(max_length=2, required=False)
    timezone = serializers.CharField(max_length=64, required=False)
    retention_days = serializers.IntegerField(min_value=1, max_value=36500, required=False)
    is_demo = serializers.BooleanField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs:
            raise serializers.ValidationError("Aucun champ à modifier.")
        return attrs


STATUS_ACTIONS = ("activate", "suspend", "reactivate", "archive")


class StatusChangeSerializer(serializers.Serializer[Any]):
    action = serializers.ChoiceField(choices=STATUS_ACTIONS)
    reason = serializers.CharField(max_length=services.MAX_REASON_LENGTH, required=False, allow_blank=True)


class AuthorizationCreateSerializer(serializers.Serializer[Any]):
    reference = serializers.CharField(max_length=100)
    scope = serializers.CharField(max_length=2000)
    valid_from = serializers.DateField()
    valid_until = serializers.DateField(required=False, allow_null=True, default=None)


class InstitutionalAdminSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


class CreatedAccountSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    email = serializers.EmailField()


class ReasonSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=services.MAX_REASON_LENGTH)


# --- Présentation -----------------------------------------------------------------------------------


def _authorization(a: OrganizationAuthorization) -> dict[str, Any]:
    return {
        "id": str(a.pk),
        "reference": a.reference,
        "scope": a.scope,
        "valid_from": _iso(a.valid_from),
        "valid_until": _iso(a.valid_until),
        "created_at": _iso(a.created_at),
    }


def _organization(view: selectors.OrganizationView, *, detail: bool = False) -> dict[str, Any]:
    o, current = view.organization, view.current_authorization
    body: dict[str, Any] = {
        "id": str(o.pk),
        "name": o.name,
        "short_name": o.short_name,
        "type": o.type,
        "status": o.status,
        "country_code": o.country_code,
        "timezone": o.timezone,
        "deployment_mode": o.deployment_mode,
        "is_demo": o.is_demo,
        "users_count": view.users_count,
        "authorization_reference": current.reference if current else None,
        "valid_from": _iso(current.valid_from) if current else None,
        "valid_until": _iso(current.valid_until) if current else None,
        "created_at": _iso(o.created_at),
    }
    if detail:
        body["retention_days"] = o.retention_days
        body["authorizations"] = [
            _authorization(a) for a in sorted(view.authorizations, key=lambda a: a.valid_from, reverse=True)
        ]
    return body


def _access_request(r: AccessRequest) -> dict[str, Any]:
    return {
        "id": str(r.pk),
        "organization_name": r.organization_name,
        "requester_name": r.requester_name,
        "requester_role": r.requester_role,
        "email": r.email,
        "request_type": r.request_type,
        "created_at": _iso(r.created_at),
    }


# --- Public -----------------------------------------------------------------------------------------

# Correspondance champs du formulaire P1 → champs du modèle (erreurs renvoyées sous les noms du formulaire).
FORM_TO_MODEL = {
    "organization": "organization_name",
    "role": "requester_role",
    "name": "requester_name",
    "email": "email",
    "phone": "phone",
    "request_type": "request_type",
    "message": "message",
}


class PublicAccessRequestView(RBIAPIView):
    public = True
    throttle_classes = (ScopedRateThrottle, AnonRateThrottle)
    throttle_scope = "access_request"

    @extend_schema(
        tags=[PUBLIC_TAG],
        summary="Demander une démonstration ou un accès",
        description="N'ouvre aucun droit et ne crée aucun compte : la demande alimente la file du Super "
        "Administrateur.",
        request=PublicAccessRequestSerializer,
        responses={201: DetailSerializer, 400: PROBLEM, 429: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        data = _valid(PublicAccessRequestSerializer, self.json_body(request))
        values = {model: data[form].strip() for form, model in FORM_TO_MODEL.items()}
        values["email"] = values["email"].lower()
        from django.core.exceptions import ValidationError as ModelValidationError

        try:
            services.submit_access_request(**values, consent=True)
        except ModelValidationError as exc:
            reverse = {model: form for form, model in FORM_TO_MODEL.items()}
            errors = {
                reverse.get(field, "non_field_errors"): msgs for field, msgs in exc.message_dict.items()
            }
            raise ValidationError(errors) from exc
        return Response({"detail": "Demande enregistrée."}, status=201)


# --- Son organisme -----------------------------------------------------------------------------------


class OwnOrganizationView(RBIAPIView):
    permission = "organization.view"

    @extend_schema(tags=[ORG_TAG], summary="Son organisme", responses={200: OrganizationSerializer})
    def get(self, request: Request) -> Response:
        return Response(_organization(selectors.describe_own_organization(get_current_tenant())))


# --- Plateforme --------------------------------------------------------------------------------------


def _scope(request: Request, purpose: str, permission: str = MANAGE_ORGANIZATIONS) -> PlatformScope:
    return platform_scope(request.user, purpose=purpose, permission=permission)


def _detail(scope: PlatformScope, organization_id: uuid.UUID) -> dict[str, Any]:
    return _organization(selectors.describe_organizations(scope, organization_id)[0], detail=True)


class PlatformOrganizationsView(RBIAPIView):
    permission = MANAGE_ORGANIZATIONS

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Registre des organismes et demandes en attente",
        operation_id="platform_organizations_list",
        responses={200: PlatformRegistrySerializer},
    )
    def get(self, request: Request) -> Response:
        scope = _scope(request, "registre des organismes")
        return Response(
            {
                "organizations": [_organization(v) for v in selectors.describe_organizations(scope)],
                "access_requests": [_access_request(r) for r in selectors.pending_access_requests(scope)],
            }
        )

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Enregistrer un organisme (EN_ATTENTE)",
        request=OrganizationCreateSerializer,
        responses={201: OrganizationDetailSerializer, 400: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        data = _valid(OrganizationCreateSerializer, self.json_body(request))
        scope = _scope(request, "enregistrement d'un organisme")
        request_id = data.pop("access_request_id")
        access_request = selectors.get_pending_access_request(scope, request_id) if request_id else None
        organization = services.register_organization(scope, **data, access_request=access_request)
        return Response(_detail(scope, organization.pk), status=201)


class PlatformOrganizationDetailView(RBIAPIView):
    permission = MANAGE_ORGANIZATIONS

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Fiche d'un organisme",
        responses={200: OrganizationDetailSerializer, 404: PROBLEM},
    )
    def get(self, request: Request, organization_id: uuid.UUID) -> Response:
        return Response(_detail(_scope(request, "fiche d'un organisme"), organization_id))

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Modifier l'identité ou les paramètres d'un organisme",
        request=OrganizationUpdateSerializer,
        responses={200: OrganizationDetailSerializer, 400: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def patch(self, request: Request, organization_id: uuid.UUID) -> Response:
        data = _valid(OrganizationUpdateSerializer, self.json_body(request))
        scope = _scope(request, "modification d'un organisme")
        services.update_organization(scope, selectors.get_organization(scope, organization_id), **data)
        return Response(_detail(scope, organization_id))


class PlatformOrganizationStatusView(RBIAPIView):
    permission = MANAGE_ORGANIZATIONS

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Changer le statut d'un organisme",
        description="activate (AUTORISÉE → ACTIVE), suspend, reactivate, archive (motif obligatoire pour les "
        "trois derniers). L'autorisation initiale passe par POST …/authorizations.",
        request=StatusChangeSerializer,
        responses={200: OrganizationDetailSerializer, 400: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def post(self, request: Request, organization_id: uuid.UUID) -> Response:
        data = _valid(StatusChangeSerializer, self.json_body(request))
        scope = _scope(request, f"statut d'un organisme ({data['action']})")
        organization = selectors.get_organization(scope, organization_id)
        reason = data.get("reason", "")
        try:
            if data["action"] == "activate":
                services.activate_organization(scope, organization)
            elif data["action"] == "suspend":
                services.suspend_organization(scope, organization, reason=reason)
            elif data["action"] == "reactivate":
                services.reactivate_organization(scope, organization, reason=reason)
            else:
                services.archive_organization(scope, organization, reason=reason)
        except InvalidTransition:
            raise
        except ValueError as exc:
            raise _business_errors(exc, "reason") from exc
        return Response(_detail(scope, organization_id))


class PlatformOrganizationAuthorizationsView(RBIAPIView):
    permission = MANAGE_ORGANIZATIONS

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Enregistrer une autorisation formelle",
        description="Pour un organisme EN_ATTENTE : autorisation initiale et passage en AUTORISÉE. Sinon : "
        "renouvellement ou avenant, sans changement de statut.",
        request=AuthorizationCreateSerializer,
        responses={201: OrganizationDetailSerializer, 400: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def post(self, request: Request, organization_id: uuid.UUID) -> Response:
        data = _valid(AuthorizationCreateSerializer, self.json_body(request))
        scope = _scope(request, "autorisation d'un organisme")
        organization = selectors.get_organization(scope, organization_id)
        arguments = {
            "reference": data["reference"],
            "scope_text": data["scope"],
            "valid_from": data["valid_from"],
            "valid_until": data["valid_until"],
        }
        if organization.status == Organization.Status.EN_ATTENTE:
            services.authorize_organization(scope, organization, **arguments)
        else:
            services.add_authorization(scope, organization, **arguments)
        return Response(_detail(scope, organization_id), status=201)


class PlatformInstitutionalAdminView(RBIAPIView):
    permission = INSTITUTIONAL_ADMINS_PERMISSION

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Désigner le premier Administrateur institutionnel",
        description="Organisme AUTORISÉ ou ACTIF. Compte sans mot de passe utilisable : l'invitation passe "
        "par le lien de réinitialisation ; MFA exigée à la première connexion.",
        request=InstitutionalAdminSerializer,
        responses={201: CreatedAccountSerializer, 400: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def post(self, request: Request, organization_id: uuid.UUID) -> Response:
        from django.db import IntegrityError

        data = _valid(InstitutionalAdminSerializer, self.json_body(request))
        scope = _scope(request, "désignation d'un administrateur", INSTITUTIONAL_ADMINS_PERMISSION)
        organization = selectors.get_organization_for_admin_designation(scope, organization_id)
        try:
            user = create_institutional_admin(
                scope,
                organization,
                email=data["email"].strip().lower(),
                first_name=data["first_name"].strip(),
                last_name=data["last_name"].strip(),
            )
        except IntegrityError as exc:
            record_event(  # refus visible des auditeurs de la plateforme
                "user.create_institutional_admin",
                outcome="failure",
                actor_id=scope.actor_id,
                scope="platform",
                object_type="organization",
                object_id=organization.pk,
                details={"reason": "email_unavailable", "demo": organization.is_demo},
            )
            raise ValidationError({"email": ["Cette adresse ne peut pas être utilisée."]}) from exc
        return Response({"id": str(user.pk), "email": user.email}, status=201)


class PlatformAccessRequestRejectView(RBIAPIView):
    permission = MANAGE_ORGANIZATIONS

    @extend_schema(
        tags=[PLATFORM_TAG],
        summary="Rejeter une demande d'accès",
        request=ReasonSerializer,
        responses={200: AccessRequestSerializer, 400: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def post(self, request: Request, request_id: uuid.UUID) -> Response:
        data = _valid(ReasonSerializer, self.json_body(request))
        scope = _scope(request, "rejet d'une demande d'accès")
        access_request = selectors.get_pending_access_request(scope, request_id)
        try:
            rejected = services.reject_access_request(scope, access_request, reason=data["reason"])
        except InvalidTransition:
            raise
        except ValueError as exc:
            raise _business_errors(exc, "reason") from exc
        return Response(_access_request(rejected))
