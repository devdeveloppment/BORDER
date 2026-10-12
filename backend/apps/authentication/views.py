"""API d'authentification (/api/v1/auth/*) et profil courant (/api/v1/me) — contrat du frontend P1.

P2.8 : vues DRF (politique déclarée, erreurs RFC 9457, documentation OpenAPI), mêmes services et mêmes
réponses qu'en P2.5. La protection CSRF du middleware s'applique à toutes les méthodes non sûres, connexion
comprise (aucune exemption) ; le jeton s'obtient par ``GET /api/v1/auth/csrf``. Aucune réponse ne contient de
mot de passe ; le secret TOTP et les codes de secours ne sont renvoyés qu'une fois, avec
``Cache-Control: no-store``.
"""

from __future__ import annotations

from typing import Any

from django.middleware.csrf import get_token
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api.errors import ProblemSerializer
from apps.core.api.views import RBIAPIView, no_content
from apps.organizations.tenancy import current_tenant_or_none
from apps.users.rbac import requires_mfa
from apps.users.selectors import describe_access

from . import mfa, services

TAG = "Authentification"
PROBLEM = OpenApiResponse(ProblemSerializer, description="Erreur (RFC 9457)")


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


# --- Schémas (documentation ; la validation métier reste dans les services P2.5) -------------------------


class LoginRequest(serializers.Serializer[Any]):
    email = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})


class StepResponse(serializers.Serializer[Any]):
    step = serializers.ChoiceField(choices=[s.value for s in services.LoginStep])


class MfaVerifyRequest(serializers.Serializer[Any]):
    code = serializers.CharField(help_text="Code TOTP à 6 chiffres ou code de secours.")


class MfaVerifyResponse(StepResponse):
    backup_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Après un enrôlement : affichés une seule fois.",
    )


class EnrollmentResponse(serializers.Serializer[Any]):
    otpauth_uri = serializers.CharField()
    secret = serializers.CharField(help_text="Renvoyé une seule fois, jamais journalisé.")


class EmailRequest(serializers.Serializer[Any]):
    email = serializers.CharField()


class DetailResponse(serializers.Serializer[Any]):
    detail = serializers.CharField()


class ResetConfirmRequest(serializers.Serializer[Any]):
    token = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})


class PasswordChangeRequest(serializers.Serializer[Any]):
    current_password = serializers.CharField(style={"input_type": "password"})
    new_password = serializers.CharField(style={"input_type": "password"})


class PasswordRequest(serializers.Serializer[Any]):
    password = serializers.CharField(style={"input_type": "password"})


class CodeRequest(serializers.Serializer[Any]):
    code = serializers.CharField()


class BackupCodesResponse(serializers.Serializer[Any]):
    backup_codes = serializers.ListField(child=serializers.CharField())


class OrganizationSummary(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    short_name = serializers.CharField()
    type = serializers.CharField()
    status = serializers.CharField()
    country_code = serializers.CharField()
    timezone = serializers.CharField()
    deployment_mode = serializers.CharField()
    is_demo = serializers.BooleanField()


class CurrentUserResponse(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField())
    permissions = serializers.ListField(child=serializers.CharField())
    organization = OrganizationSummary(allow_null=True)
    mfa_enabled = serializers.BooleanField()
    mfa_required = serializers.BooleanField()
    assigned_post_ids = serializers.ListField(
        child=serializers.UUIDField(), help_text="Toujours vide tant que le module des postes n'existe pas."
    )
    last_login = serializers.DateTimeField(allow_null=True)


def organization_summary(organization: Any) -> dict[str, Any] | None:
    if organization is None:
        return None
    return {
        "id": str(organization.pk),
        "name": organization.name,
        "short_name": organization.short_name,
        "type": organization.type,
        "status": organization.status,
        "country_code": organization.country_code,
        "timezone": organization.timezone,
        "deployment_mode": organization.deployment_mode,
        "is_demo": organization.is_demo,
    }


class AuthView(RBIAPIView):
    abstract = True
    lenient_body = True


# --- Public : connexion et récupération -------------------------------------------------------------


class CsrfView(AuthView):
    public = True

    @extend_schema(tags=[TAG], summary="Obtenir le cookie CSRF", responses={204: None})
    def get(self, request: Request) -> Response:
        get_token(request._request)  # le middleware CSRF pose le cookie csrftoken sur la réponse
        return no_content()


class LoginView(AuthView):
    public = True

    @extend_schema(
        tags=[TAG],
        summary="Connexion par mot de passe",
        request=LoginRequest,
        responses={200: StepResponse, 401: PROBLEM, 403: PROBLEM, 429: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        data = self.json_body(request)
        step = services.login_with_password(request._request, _text(data, "email"), _text(data, "password"))
        return Response({"step": step.value})


class MfaEnrollView(AuthView):
    public = True  # étape « mot de passe vérifié » : aucune session complète n'existe encore

    @extend_schema(
        tags=[TAG],
        summary="Démarrer l'enrôlement TOTP",
        request=None,
        responses={200: EnrollmentResponse, 401: PROBLEM, 403: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        return Response(services.start_enrollment(request._request))


class MfaVerifyView(AuthView):
    public = True

    @extend_schema(
        tags=[TAG],
        summary="Vérifier le second facteur",
        request=MfaVerifyRequest,
        responses={200: MfaVerifyResponse, 400: PROBLEM, 401: PROBLEM, 429: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        step, backup_codes = services.verify_mfa(request._request, _text(self.json_body(request), "code"))
        payload: dict[str, Any] = {"step": step.value}
        if backup_codes:
            payload["backup_codes"] = backup_codes  # affichés une seule fois, jamais conservés en clair
        return Response(payload)


class LogoutView(AuthView):
    public = True  # ferme aussi une étape « en attente de MFA »

    @extend_schema(tags=[TAG], summary="Déconnexion", request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        services.logout_session(request._request)
        return no_content()


class PasswordResetView(AuthView):
    public = True

    @extend_schema(
        tags=[TAG],
        summary="Demander un lien de réinitialisation",
        request=EmailRequest,
        responses={202: DetailResponse},
    )
    def post(self, request: Request) -> Response:
        services.request_password_reset(request._request, _text(self.json_body(request), "email"))
        return Response(
            {"detail": "Si un compte correspond, un lien de réinitialisation a été envoyé."}, status=202
        )


class PasswordResetConfirmView(AuthView):
    public = True

    @extend_schema(
        tags=[TAG],
        summary="Définir un nouveau mot de passe par lien",
        request=ResetConfirmRequest,
        responses={204: None, 400: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        data = self.json_body(request)
        services.confirm_password_reset(_text(data, "token"), _text(data, "password"))
        return no_content()


# --- Authentifié (session complète, MFA comprise) ----------------------------------------------------


class MeView(AuthView):
    authenticated = True

    @extend_schema(tags=[TAG], summary="Profil et organisme courants", responses={200: CurrentUserResponse})
    def get(self, request: Request) -> Response:
        user = self.actor(request)
        access = describe_access(user, current_tenant_or_none())
        return Response(
            {
                "id": str(user.pk),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "roles": access["roles"],
                "permissions": access["permissions"],
                "organization": organization_summary(user.organization if user.organization_id else None),
                "mfa_enabled": mfa.mfa_enabled(user),
                "mfa_required": requires_mfa(user),
                "assigned_post_ids": [],  # postes d'affectation : avec le module des postes frontaliers
                "last_login": user.last_login.isoformat() if user.last_login else None,
            }
        )


class PasswordChangeView(AuthView):
    authenticated = True

    @extend_schema(
        tags=[TAG],
        summary="Changer son mot de passe",
        request=PasswordChangeRequest,
        responses={204: None, 400: PROBLEM, 401: PROBLEM, 429: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        data = self.json_body(request)
        services.change_password(
            request._request, _text(data, "current_password"), _text(data, "new_password")
        )
        return no_content()


class SessionsRevokeOthersView(AuthView):
    authenticated = True

    @extend_schema(
        tags=[TAG],
        summary="Fermer toutes ses autres sessions",
        request=PasswordRequest,
        responses={204: None, 401: PROBLEM, 429: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        services.revoke_other_sessions(request._request, _text(self.json_body(request), "password"))
        return no_content()


class MfaTotpRenewView(AuthView):
    authenticated = True

    @extend_schema(
        tags=[TAG],
        summary="Activer ou renouveler son TOTP",
        request=PasswordRequest,
        responses={200: EnrollmentResponse, 401: PROBLEM, 429: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        return Response(
            services.renew_totp_start(request._request, _text(self.json_body(request), "password"))
        )


class MfaTotpRenewConfirmView(AuthView):
    authenticated = True

    @extend_schema(
        tags=[TAG],
        summary="Confirmer le nouveau TOTP",
        request=CodeRequest,
        responses={200: BackupCodesResponse, 400: PROBLEM, 401: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        codes = services.renew_totp_confirm(request._request, _text(self.json_body(request), "code"))
        return Response({"backup_codes": codes})


class MfaBackupCodesView(AuthView):
    authenticated = True

    @extend_schema(
        tags=[TAG],
        summary="Régénérer ses codes de secours",
        request=PasswordRequest,
        responses={200: BackupCodesResponse, 401: PROBLEM, 403: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        codes = services.regenerate_backup_codes(request._request, _text(self.json_body(request), "password"))
        return Response({"backup_codes": codes})


class MfaDisableView(AuthView):
    authenticated = True

    @extend_schema(
        tags=[TAG],
        summary="Désactiver sa MFA (rôles sans MFA obligatoire)",
        request=PasswordRequest,
        responses={204: None, 401: PROBLEM, 403: PROBLEM},
    )
    def post(self, request: Request) -> Response:
        services.disable_mfa(request._request, _text(self.json_body(request), "password"))
        return no_content()
