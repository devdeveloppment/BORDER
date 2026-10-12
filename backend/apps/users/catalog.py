"""Catalogue RBAC de référence : permissions atomiques et rôles par défaut.

Spécification interne non publiée §7.2, §7.3, §14.3.

Source de vérité unique. La base est synchronisée sur ce catalogue après chaque ``migrate``
(``apps.users.rbac_sync``) ; les rôles par défaut ne se modifient pas en base.

Deux portées strictement séparées (contrainte PostgreSQL) :
- ``platform`` : gouvernance de RBI, exercée par des comptes plateforme (sans organisme) ;
- ``organization`` : droits exercés exclusivement dans l'organisme de l'utilisateur.

Codes alignés sur le contrat du frontend P1 (``frontend/src/lib/permissions.ts``). Écarts : ``users.view``
(lecture des utilisateurs par l'Auditeur, §7.3) et le découpage plateforme (``platform.audit``,
``platform.institutional_admins``) ; l'ancien ``audit.view`` du Super Admin devient ``platform.audit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Scope = Literal["platform", "organization"]


@dataclass(frozen=True, slots=True)
class PermissionDef:
    code: str
    scope: Scope
    description: str

    @property
    def module(self) -> str:
        return self.code.split(".", 1)[0]


@dataclass(frozen=True, slots=True)
class RoleDef:
    code: str
    scope: Scope
    name: str
    permissions: frozenset[str]
    mfa_required: bool


PERMISSIONS: tuple[PermissionDef, ...] = (
    # --- Plateforme ---------------------------------------------------------------------------
    PermissionDef(
        "platform.organizations", "platform", "Autoriser, activer, suspendre, archiver les organismes"
    ),
    PermissionDef(
        "platform.institutional_admins",
        "platform",
        "Créer le premier Administrateur institutionnel d'un organisme",
    ),
    PermissionDef("platform.health", "platform", "Consulter la page System Health"),
    PermissionDef(
        "platform.audit", "platform", "Consulter le journal d'audit et les journaux techniques plateforme"
    ),
    # --- Organisme : consultation -------------------------------------------------------------
    PermissionDef("dashboard.view", "organization", "Consulter le tableau de bord"),
    PermissionDef("map.view", "organization", "Consulter la carte"),
    PermissionDef("border_posts.view", "organization", "Consulter les postes frontaliers"),
    PermissionDef("activities.view", "organization", "Consulter le registre des activités"),
    PermissionDef("alerts.view", "organization", "Consulter les alertes et leurs explications"),
    PermissionDef("analytics.view", "organization", "Consulter les analyses et statistiques"),
    PermissionDef("reports.view", "organization", "Consulter les rapports"),
    PermissionDef("settings.view", "organization", "Consulter les paramètres et seuils"),
    PermissionDef("audit.view", "organization", "Consulter le journal d'audit de l'organisme"),
    PermissionDef("organization.view", "organization", "Consulter la fiche de son organisme"),
    PermissionDef("users.view", "organization", "Consulter les utilisateurs et leurs rôles"),
    # --- Organisme : actions opérationnelles --------------------------------------------------
    PermissionDef("activities.create", "organization", "Saisir des activités et événements"),
    PermissionDef("activities.export", "organization", "Exporter le registre des activités"),
    PermissionDef("alerts.take", "organization", "Prendre en charge une alerte (jusqu'à EXAMINÉE)"),
    PermissionDef("alerts.comment", "organization", "Ajouter une observation à une alerte"),
    PermissionDef("alerts.assign", "organization", "Assigner une alerte"),
    PermissionDef(
        "alerts.decide", "organization", "Valider ou classer une alerte (CONFIRMÉE, ÉCARTÉE, CLÔTURÉE)"
    ),
    PermissionDef("analytics.what_if", "organization", "Lancer des scénarios what-if"),
    PermissionDef("reports.generate", "organization", "Générer des rapports"),
    PermissionDef("imports.run", "organization", "Importer des données"),
    # --- Organisme : administration institutionnelle ------------------------------------------
    PermissionDef("border_posts.manage", "organization", "Configurer les postes frontaliers"),
    PermissionDef("sources.manage", "organization", "Déclarer et configurer les sources de données"),
    PermissionDef("settings.manage", "organization", "Modifier paramètres, seuils et pondérations"),
    PermissionDef(
        "users.manage", "organization", "Créer, activer, désactiver les utilisateurs ; attribuer les rôles"
    ),
)

_VIEW = frozenset(
    {
        "dashboard.view",
        "map.view",
        "border_posts.view",
        "activities.view",
        "alerts.view",
        "analytics.view",
        "reports.view",
        "settings.view",
    }
)

ROLES: tuple[RoleDef, ...] = (
    # Aucune donnée opérationnelle hors procédure d'accès sous mandat (§7.1).
    RoleDef(
        "SUPER_ADMIN",
        "platform",
        "Super Administrateur",
        frozenset(
            {"platform.organizations", "platform.institutional_admins", "platform.health", "platform.audit"}
        ),
        mfa_required=True,
    ),
    # « Un auditeur plateforme peut être désigné pour l'audit du niveau plateforme » (§7.2 F) ;
    # le code d'un rôle est unique par portée (§14.3).
    RoleDef("AUDITOR", "platform", "Auditeur plateforme", frozenset({"platform.audit"}), mfa_required=True),
    RoleDef(
        "ORG_ADMIN",
        "organization",
        "Administrateur institutionnel",
        _VIEW
        | {
            "audit.view",
            "organization.view",
            "users.view",
            "activities.create",
            "activities.export",
            "alerts.take",
            "alerts.comment",
            "alerts.assign",
            "alerts.decide",
            "reports.generate",
            "imports.run",
            "border_posts.manage",
            "sources.manage",
            "settings.manage",
            "users.manage",
        },
        mfa_required=True,
    ),
    RoleDef(
        "SUPERVISOR",
        "organization",
        "Superviseur",
        _VIEW
        | {
            "activities.export",
            "alerts.take",
            "alerts.comment",
            "alerts.assign",
            "alerts.decide",
            "analytics.what_if",
            "reports.generate",
        },
        mfa_required=True,
    ),
    # Import interdit par défaut (ADR 0001 · P10).
    RoleDef(
        "AGENT",
        "organization",
        "Agent opérationnel",
        frozenset(
            {
                "dashboard.view",
                "map.view",
                "border_posts.view",
                "activities.view",
                "alerts.view",
                "activities.create",
                "alerts.take",
                "alerts.comment",
            }
        ),
        mfa_required=False,
    ),
    RoleDef(
        "ANALYST",
        "organization",
        "Analyste",
        _VIEW | {"activities.export", "analytics.what_if", "reports.generate"},
        mfa_required=False,
    ),
    # Lecture seule stricte : aucune permission d'action (vérifié par test).
    RoleDef(
        "AUDITOR", "organization", "Auditeur", _VIEW | {"audit.view", "organization.view", "users.view"}, True
    ),
)

PERMISSIONS_BY_CODE: dict[str, PermissionDef] = {p.code: p for p in PERMISSIONS}
ROLES_BY_KEY: dict[tuple[str, Scope], RoleDef] = {(r.code, r.scope): r for r in ROLES}

# Rôle exigé pour activer un organisme ; son dernier titulaire actif ne peut pas être retiré.
INSTITUTIONAL_ADMIN = "ORG_ADMIN"


def validate_catalog() -> None:
    """Cohérence interne : appelée au démarrage de l'application et par les tests."""
    codes = [p.code for p in PERMISSIONS]
    if len(codes) != len(set(codes)):
        raise ValueError("Code de permission dupliqué dans le catalogue.")
    if len(ROLES_BY_KEY) != len(ROLES):
        raise ValueError("Rôle dupliqué pour une même portée.")
    for role in ROLES:
        for code in role.permissions:
            permission = PERMISSIONS_BY_CODE.get(code)
            if permission is None:
                raise ValueError(f"{role.code} : permission inconnue {code}")
            if permission.scope != role.scope:
                raise ValueError(
                    f"{role.code} ({role.scope}) : permission {code} de portée {permission.scope}"
                )
