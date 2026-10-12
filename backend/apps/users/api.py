"""API des comptes et rôles de l'organisme (écrans 23-24, §9.12, §15.2 « /users, /roles »).

L'organisme est TOUJOURS celui du contexte serveur (utilisateur authentifié) : aucun identifiant d'organisme
n'est lu dans l'URL, les paramètres ni le corps. Un compte d'un autre organisme répond 404 (§15.1). Toute
écriture passe par les services P2.4 (règles d'auto-administration, dernier administrateur, rôles
d'organisme seulement), eux-mêmes audités (P2.7).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import IntegrityError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.audit.services import record_event
from apps.authentication.services import reset_user_mfa
from apps.core.api.errors import ProblemSerializer
from apps.core.api.views import RBIAPIView, by_method, no_content
from apps.organizations.tenancy import TenantContext, get_current_tenant

from . import services
from .catalog import ROLES
from .models import User
from .selectors import OrganizationUserRow, organization_user_rows

TAG = "Comptes et rôles"
PROBLEM = OpenApiResponse(ProblemSerializer, description="Erreur (RFC 9457)")
ORGANIZATION_ROLES = [r.code for r in ROLES if r.scope == "organization"]


class OrgUserSerializer(serializers.Serializer[Any]):
    """Contrat P1 ``OrgUser``."""

    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    roles = serializers.ListField(child=serializers.ChoiceField(choices=ORGANIZATION_ROLES))
    is_active = serializers.BooleanField()
    mfa_enabled = serializers.BooleanField()
    last_login = serializers.DateTimeField(allow_null=True)
    assigned_posts = serializers.ListField(
        child=serializers.CharField(), help_text="Toujours vide tant que le module des postes n'existe pas."
    )


class UserCreateSerializer(serializers.Serializer[Any]):
    email = serializers.EmailField(max_length=254)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=ORGANIZATION_ROLES),
        max_length=len(ORGANIZATION_ROLES),
        default=list,
    )

    def validate_roles(self, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Rôle en double.")
        return value


class UserUpdateSerializer(serializers.Serializer[Any]):
    is_active = serializers.BooleanField()


class RoleAssignSerializer(serializers.Serializer[Any]):
    role = serializers.ChoiceField(choices=ORGANIZATION_ROLES)


class RoleSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    name = serializers.CharField()
    mfa_required = serializers.BooleanField()
    permissions = serializers.ListField(child=serializers.CharField())


def _payload(row: OrganizationUserRow) -> dict[str, Any]:
    user = row.user
    return {
        "id": str(user.pk),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "roles": row.roles,
        "is_active": user.is_active,
        "mfa_enabled": row.mfa_enabled,
        "last_login": user.last_login.isoformat().replace("+00:00", "Z") if user.last_login else None,
        "assigned_posts": [],
    }


def _one(actor: User, context: TenantContext, user_id: uuid.UUID) -> dict[str, Any]:
    return _payload(organization_user_rows(actor, context, user_id)[0])


def _valid(serializer_class: type[serializers.Serializer[Any]], data: Any) -> dict[str, Any]:
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


class UsersView(RBIAPIView):
    permission = by_method(GET="users.view", POST="users.manage")

    @extend_schema(
        tags=[TAG], summary="Comptes de son organisme", responses={200: OrgUserSerializer(many=True)}
    )
    def get(self, request: Request) -> Response:
        rows = organization_user_rows(self.actor(request), get_current_tenant())
        return Response([_payload(row) for row in rows])

    @extend_schema(
        tags=[TAG],
        summary="Créer un compte dans son organisme",
        description=(
            "Compte sans mot de passe utilisable : l'invitation passe par le lien de réinitialisation."
        ),
        request=UserCreateSerializer,
        responses={201: OrgUserSerializer, 400: PROBLEM, 403: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        data = _valid(UserCreateSerializer, self.json_body(request))
        context = get_current_tenant()
        try:
            user = services.create_organization_user(
                self.actor(request),
                context,
                email=data["email"].strip().lower(),
                first_name=data["first_name"].strip(),
                last_name=data["last_name"].strip(),
                roles=tuple(data["roles"]),
            )
        except IntegrityError as exc:
            # Unicité globale de l'adresse : limite documentée (ADR 0008, limite 2). Chaque refus
            # est journalisé : des essais répétés d'adresses deviennent visibles des auditeurs.
            record_event(
                "user.create",
                outcome="failure",
                actor_id=self.actor(request).pk,
                organization_id=context.organization_id,
                details={"reason": "email_unavailable"},
            )
            raise ValidationError({"email": ["Cette adresse ne peut pas être utilisée."]}) from exc
        return Response(_one(self.actor(request), context, user.pk), status=201)


class UserDetailView(RBIAPIView):
    permission = by_method(GET="users.view", PATCH="users.manage")

    @extend_schema(
        tags=[TAG], summary="Un compte de son organisme", responses={200: OrgUserSerializer, 404: PROBLEM}
    )
    def get(self, request: Request, user_id: uuid.UUID) -> Response:
        return Response(_one(self.actor(request), get_current_tenant(), user_id))

    @extend_schema(
        tags=[TAG],
        summary="Activer ou désactiver un compte",
        request=UserUpdateSerializer,
        responses={200: OrgUserSerializer, 403: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def patch(self, request: Request, user_id: uuid.UUID) -> Response:
        data = _valid(UserUpdateSerializer, self.json_body(request))
        context = get_current_tenant()
        services.set_user_active(self.actor(request), context, user_id, active=data["is_active"])
        return Response(_one(self.actor(request), context, user_id))


class UserRolesView(RBIAPIView):
    permission = "users.manage"

    @extend_schema(
        tags=[TAG],
        summary="Attribuer un rôle d'organisme",
        request=RoleAssignSerializer,
        responses={200: OrgUserSerializer, 400: PROBLEM, 403: PROBLEM, 404: PROBLEM},
    )
    def post(self, request: Request, user_id: uuid.UUID) -> Response:
        data = _valid(RoleAssignSerializer, self.json_body(request))
        context = get_current_tenant()
        services.assign_role(self.actor(request), context, user_id, data["role"])
        return Response(_one(self.actor(request), context, user_id))


class UserRoleDetailView(RBIAPIView):
    permission = "users.manage"

    @extend_schema(
        tags=[TAG],
        summary="Retirer un rôle d'organisme",
        responses={204: None, 403: PROBLEM, 404: PROBLEM, 409: PROBLEM},
    )
    def delete(self, request: Request, user_id: uuid.UUID, role: str) -> Response:
        if role not in ORGANIZATION_ROLES:
            raise ValidationError({"role": ["Rôle inconnu."]})
        services.revoke_role(self.actor(request), get_current_tenant(), user_id, role)
        return no_content()


class UserMfaResetView(RBIAPIView):
    permission = "users.manage"

    @extend_schema(
        tags=[TAG],
        summary="Réinitialiser la MFA d'un compte",
        description=(
            "Supprime ses facteurs et ferme ses sessions ; il se ré-enrôlera à la prochaine connexion."
        ),
        request=None,
        responses={204: None, 403: PROBLEM, 404: PROBLEM},
    )
    def post(self, request: Request, user_id: uuid.UUID) -> Response:
        reset_user_mfa(self.actor(request), get_current_tenant(), user_id)
        return no_content()


class RolesView(RBIAPIView):
    permission = "users.view"

    @extend_schema(
        tags=[TAG], summary="Rôles attribuables dans l'organisme", responses={200: RoleSerializer(many=True)}
    )
    def get(self, request: Request) -> Response:
        return Response(
            [
                {
                    "code": r.code,
                    "name": r.name,
                    "mfa_required": r.mfa_required,
                    "permissions": sorted(r.permissions),
                }
                for r in ROLES
                if r.scope == "organization"
            ]
        )
