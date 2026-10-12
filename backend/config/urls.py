"""Routes de RBI : API REST v1 uniquement (/api/v1/), refus par défaut (ADR 0007, ADR 0010).

Chaque vue déclare sa politique d'accès (public, authentifié, permission RBAC) ; un test vérifie la table
complète des routes (apps/core/tests/test_api_routes.py). Les modules métier sans modèle (tableau de bord,
postes, activités, alertes, analyses, rapports, notifications, paramètres) ne sont PAS exposés : aucune donnée
simulée n'est servie comme réelle (rapport P2.8).
"""

from django.urls import URLPattern, URLResolver, include, path

from apps.audit import api as audit
from apps.authentication.views import MeView
from apps.core.api.schema_view import SchemaView
from apps.organizations import api as organizations
from apps.users import api as users

v1: list[URLPattern | URLResolver] = [
    path("health/", include("apps.health.urls")),
    path("auth/", include("apps.authentication.urls")),
    path("me", MeView.as_view(), name="me"),
    path("schema", SchemaView.as_view(), name="schema"),
    # Public
    path(
        "public/access-requests",
        organizations.PublicAccessRequestView.as_view(),
        name="public-access-requests",
    ),
    # Organisme (contexte serveur)
    path("organization", organizations.OwnOrganizationView.as_view(), name="organization"),
    path("users", users.UsersView.as_view(), name="users"),
    path("users/<uuid:user_id>", users.UserDetailView.as_view(), name="user-detail"),
    path("users/<uuid:user_id>/roles", users.UserRolesView.as_view(), name="user-roles"),
    path(
        "users/<uuid:user_id>/roles/<str:role>", users.UserRoleDetailView.as_view(), name="user-role-detail"
    ),
    path("users/<uuid:user_id>/mfa-reset", users.UserMfaResetView.as_view(), name="user-mfa-reset"),
    path("roles", users.RolesView.as_view(), name="roles"),
    path("audit-logs", audit.OrganizationAuditView.as_view(), name="audit-logs"),
    path("audit-logs/export", audit.OrganizationAuditExportView.as_view(), name="audit-logs-export"),
    path("audit-logs/integrity", audit.OrganizationAuditIntegrityView.as_view(), name="audit-logs-integrity"),
    # Plateforme
    path(
        "platform/organizations",
        organizations.PlatformOrganizationsView.as_view(),
        name="platform-organizations",
    ),
    path(
        "platform/organizations/<uuid:organization_id>",
        organizations.PlatformOrganizationDetailView.as_view(),
        name="platform-organization-detail",
    ),
    path(
        "platform/organizations/<uuid:organization_id>/status",
        organizations.PlatformOrganizationStatusView.as_view(),
        name="platform-organization-status",
    ),
    path(
        "platform/organizations/<uuid:organization_id>/authorizations",
        organizations.PlatformOrganizationAuthorizationsView.as_view(),
        name="platform-organization-authorizations",
    ),
    path(
        "platform/organizations/<uuid:organization_id>/institutional-admins",
        organizations.PlatformInstitutionalAdminView.as_view(),
        name="platform-institutional-admins",
    ),
    path(
        "platform/access-requests/<uuid:request_id>/reject",
        organizations.PlatformAccessRequestRejectView.as_view(),
        name="platform-access-request-reject",
    ),
    path("platform/audit-logs", audit.PlatformAuditView.as_view(), name="platform-audit-logs"),
    path(
        "platform/audit-logs/export",
        audit.PlatformAuditExportView.as_view(),
        name="platform-audit-logs-export",
    ),
    path(
        "platform/audit-logs/integrity",
        audit.PlatformAuditIntegrityView.as_view(),
        name="platform-audit-logs-integrity",
    ),
]

urlpatterns = [path("api/v1/", include(v1))]

# Erreurs hors vues de l'API : même format RFC 9457, aucun détail technique.
handler400 = "apps.core.http.bad_request"
handler403 = "apps.core.http.permission_denied"
handler404 = "apps.core.http.not_found"
handler500 = "apps.core.http.server_error"
