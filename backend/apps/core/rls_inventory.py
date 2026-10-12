"""Inventaire de sécurité des tables (P2.6, ADR 0008 ; P2.7, ADR 0009) : référence vérifiée par les tests
contre PostgreSQL.

Toute nouvelle table doit y figurer, sinon ``test_every_table_is_inventoried`` échoue. Toute table d'un modèle
``TenantScopedModel`` doit être classée ``tenant`` avec RLS et politique d'isolation, sinon un test échoue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal[
    "tenant", "platform", "identity", "mfa", "audit", "catalog", "framework", "extension", "test_only"
]

ALL_DML = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
READ_ONLY = frozenset({"SELECT"})


@dataclass(frozen=True, slots=True)
class TableSecurity:
    category: Category
    logical_owner: str
    strategy: str
    rls: bool
    policies: frozenset[str]
    app_privileges: frozenset[str]
    organization_column: str | None = None
    # INSERT accordé colonne par colonne (aucun INSERT au niveau de la table) : journal d'audit.
    insert_columns: frozenset[str] = frozenset()


def _p(*names: str) -> frozenset[str]:
    return frozenset(names)


INVENTORY: dict[str, TableSecurity] = {
    # 1. Données appartenant à un organisme ---------------------------------------------------------------
    "integrations_datasource": TableSecurity(
        "tenant",
        "organisme",
        "RLS : organization_id = app.current_org pour SELECT/INSERT/UPDATE/DELETE (USING + WITH CHECK)",
        True,
        _p("rbi_tenant_isolation"),
        ALL_DML,
        "organization_id",
    ),
    # 2. Données globales de plateforme ----------------------------------------------------------------------
    "organizations_organization": TableSecurity(
        "platform",
        "plateforme (Super Administrateur)",
        "lecture : son organisme ou opération plateforme ; écriture : platform.organizations ; jamais de "
        "suppression",
        True,
        _p("rbi_org_select", "rbi_org_insert", "rbi_org_update"),
        frozenset({"SELECT", "INSERT", "UPDATE"}),
        "id",
    ),
    "organizations_organizationauthorization": TableSecurity(
        "platform",
        "plateforme",
        "lecture : son organisme ou opération plateforme ; création : platform.organizations ; immuable",
        True,
        _p("rbi_authorization_select", "rbi_authorization_insert"),
        frozenset({"SELECT", "INSERT"}),
        "organization_id",
    ),
    "organizations_accessrequest": TableSecurity(
        "platform",
        "plateforme",
        "création publique d'une demande neuve uniquement ; lecture et traitement : platform.organizations",
        True,
        _p("rbi_access_request_select", "rbi_access_request_insert", "rbi_access_request_update"),
        frozenset({"SELECT", "INSERT", "UPDATE"}),
        "organization_id",
    ),
    # 3. Identité ------------------------------------------------------------------------------------------
    "users_user": TableSecurity(
        "identity",
        "compte (son titulaire) / organisme (ses administrateurs)",
        "lecture : soi, son organisme, ou l'e-mail recherché à la connexion ; écriture : soi (sans changer "
        "d'organisme) ou son organisme ; création : son organisme ou désignation du 1er administrateur ; "
        "jamais de suppression",
        True,
        _p("rbi_user_select", "rbi_user_insert", "rbi_user_update"),
        frozenset({"SELECT", "INSERT", "UPDATE"}),
        "organization_id",
    ),
    "users_user_role": TableSecurity(
        "identity",
        "organisme (affectations) / plateforme (rôles plateforme, maintenance uniquement)",
        "lecture : ses affectations ou celles de son organisme ; écriture : rôles d'organisme de son "
        "organisme ; "
        "désignation du 1er administrateur sous platform.institutional_admins",
        True,
        _p("rbi_user_role_select", "rbi_user_role_insert", "rbi_user_role_update", "rbi_user_role_delete"),
        ALL_DML,
        "organization_id",
    ),
    # 4. Secrets MFA ---------------------------------------------------------------------------------------
    "otp_totp_totpdevice": TableSecurity(
        "mfa",
        "compte titulaire",
        "RLS : user_id = app.current_user ; réinitialisation par un administrateur via rbi_admin_reset_mfa",
        True,
        _p("rbi_own_mfa_device"),
        ALL_DML,
    ),
    "authentication_mfa_backup_code": TableSecurity(
        "mfa",
        "compte titulaire",
        "RLS : user_id = app.current_user ; codes hachés",
        True,
        _p("rbi_own_backup_code"),
        ALL_DML,
    ),
    # 5. Journal d'audit (P2.7) : insertion seule ---------------------------------------------------------
    "audit_auditlog": TableSecurity(
        "audit",
        "organisme (ses entrées) / plateforme (entrées de portée plateforme)",
        "insertion seule : INSERT des colonnes descriptives (identifiant, horodatage et empreintes posés "
        "par le déclencheur de scellement) ; attribution limitée au contexte serveur ; lecture avec "
        "audit.view ou platform.audit revérifiée en SQL ; UPDATE/DELETE/TRUNCATE sans privilège et bloqués "
        "par déclencheur",
        True,
        _p("rbi_audit_select", "rbi_audit_insert"),
        READ_ONLY,
        "organization_id",
        insert_columns=_p(
            "scope",
            "organization_id",
            "actor_type",
            "actor_id",
            "action",
            "outcome",
            "object_type",
            "object_id",
            "old_value",
            "new_value",
            "metadata",
            "ip_address",
            "request_id",
        ),
    ),
    "audit_chain": TableSecurity(
        "audit",
        "déclencheur de scellement",
        "têtes de chaîne : écrites uniquement par le déclencheur de scellement ; lecture pour la "
        "vérification d'intégrité, mêmes conditions que le journal",
        True,
        _p("rbi_audit_chain_select"),
        READ_ONLY,
    ),
    # 6. Catalogues, tables du cadriciel, extension --------------------------------------------------------
    "users_role": TableSecurity(
        "catalog",
        "plateforme (catalogue) ; organisme pour les rôles personnalisés (V1)",
        "lecture seule : rôles par défaut ou de son organisme ; écriture : migrations (propriétaire)",
        True,
        _p("rbi_role_select"),
        READ_ONLY,
        "organization_id",
    ),
    "users_permission": TableSecurity(
        "catalog", "plateforme", "catalogue global non sensible, lecture seule", False, frozenset(), READ_ONLY
    ),
    "users_role_permission": TableSecurity(
        "catalog",
        "plateforme",
        "composition des rôles par défaut, lecture seule",
        False,
        frozenset(),
        READ_ONLY,
    ),
    "auth_group": TableSecurity(
        "framework", "Django (inutilisé : RBAC RBI)", "lecture seule", False, frozenset(), READ_ONLY
    ),
    "auth_group_permissions": TableSecurity(
        "framework", "Django (inutilisé)", "lecture seule", False, frozenset(), READ_ONLY
    ),
    "auth_permission": TableSecurity(
        "framework", "Django (inutilisé)", "lecture seule", False, frozenset(), READ_ONLY
    ),
    "django_content_type": TableSecurity(
        "framework", "Django", "lecture seule (alimentée par migrate)", False, frozenset(), READ_ONLY
    ),
    "django_migrations": TableSecurity(
        "framework",
        "Django",
        "lecture seule (vérification des migrations au démarrage)",
        False,
        frozenset(),
        READ_ONLY,
    ),
    "spatial_ref_sys": TableSecurity(
        "extension",
        "PostGIS (superutilisateur)",
        "référentiel public de projections",
        False,
        frozenset(),
        READ_ONLY,
    ),
    # Application de test (base de test uniquement) --------------------------------------------------------
    "gisprobe_probesite": TableSecurity(
        "test_only", "tests", "données géographiques fictives des tests", False, frozenset(), ALL_DML
    ),
}

# Fonctions SECURITY DEFINER : exécutables par le seul rôle applicatif, chacune revérifiant son périmètre.
DEFINER_FUNCTIONS = frozenset(
    {
        "rbi_current_user_org",
        "rbi_org_has_active_admin",
        "rbi_admin_reset_mfa",
        "rbi_audit_org_reader",
        "rbi_audit_platform_reader",
        # P2.8 (API) : statut MFA des comptes de son organisme ; décomptes de comptes par organisme.
        "rbi_org_mfa_enabled_users",
        "rbi_platform_org_user_counts",
    }
)
# Fonctions de déclencheur SECURITY DEFINER : exécutées par PostgreSQL lors de l'insertion, jamais appelables
# directement (EXECUTE retiré à tous).
TRIGGER_DEFINER_FUNCTIONS = frozenset({"rbi_audit_seal"})
