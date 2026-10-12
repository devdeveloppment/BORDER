"""Données fictives de démonstration (P2.11, commande ``seed_demo``, ADR 0013).

Périmètre validé (décisions D1 à D8) : deux organismes « Organisme Démo A » et « Organisme Démo B », leurs
autorisations et leur statut (EN_ATTENTE → AUTORISEE → ACTIVE), cinq comptes par organisme (un par rôle
institutionnel). Aucun autre modèle n'est créé ici : postes, activités, véhicules, événements, alertes et
sources de données relèvent des modules qui les implémenteront.

Garanties :
- toutes les écritures passent par les services métier, sous un ``PlatformScope`` délivré par
  ``platform_scope`` pour l'acteur désigné ; aucune écriture directe, aucun contournement de RLS ;
- le lot est planifié en lecture seule (refus avant toute écriture en cas de collision), puis appliqué
  dans une seule transaction ;
- marquage : organismes ``is_demo = true`` aux sigles déterministes ; comptes au domaine réservé ``.test`` ;
- aucun mot de passe, secret TOTP, code de récupération ni jeton : les comptes sont créés sans mot de passe
  utilisable et s'activent par le parcours « mot de passe oublié » (procédure documentée).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.core.db_scope import db_scope, identity_scope
from apps.core.maintenance import current_database_role
from apps.organizations.exceptions import PlatformAccessDenied
from apps.organizations.models import Organization
from apps.organizations.platform import (
    MANAGE_ORGANIZATIONS,
    PlatformScope,
    platform_operation,
    platform_scope,
)
from apps.organizations.selectors import list_organizations
from apps.organizations.services import (
    activate_organization,
    authorize_organization,
    register_organization,
)
from apps.organizations.tenancy import context_for_user
from apps.users.catalog import INSTITUTIONAL_ADMIN
from apps.users.models import User, UserRole
from apps.users.services import (
    INSTITUTIONAL_ADMINS_PERMISSION,
    create_institutional_admin,
    create_organization_user,
)

logger = logging.getLogger(__name__)

# Environnements explicitement autorisés (D6). Toute autre valeur, y compris absente, refuse l'exécution.
ALLOWED_ENVIRONMENTS = frozenset({"development", "test"})
DEMO_DOMAIN_SUFFIX = ".test"  # domaine réservé (RFC 2606) : aucune adresse réelle possible
DEMO_COUNTRY = "ZZ"  # code ISO non attribué : aucune localisation réelle implicite
DEMO_TIMEZONE = "UTC"
DEMO_RETENTION_DAYS = 365
DEMO_SCOPE_TEXT = "Périmètre fictif de démonstration (aucune donnée réelle)"


class SeedRefused(Exception):
    """Refus avant toute écriture : message sûr, affichable tel quel."""


class SeedFailed(Exception):
    """Échec pendant l'application : le lot est annulé, le détail reste dans les journaux serveur."""


@dataclass(frozen=True)
class AccountSpec:
    local_part: str
    role: str
    label: str


@dataclass(frozen=True)
class OrganizationSpec:
    name: str
    short_name: str
    type: str
    domain: str
    letter: str
    accounts: tuple[AccountSpec, ...] = field(default=())

    @property
    def authorization_reference(self) -> str:
        return f"DEMO-{self.letter}-AUTH"


# Un compte par rôle institutionnel (catalogue RBAC, portée « organisme »). Aucun rôle inventé.
ACCOUNTS: tuple[AccountSpec, ...] = (
    AccountSpec("admin", INSTITUTIONAL_ADMIN, "Administrateur institutionnel"),
    AccountSpec("superviseur", "SUPERVISOR", "Superviseur"),
    AccountSpec("agent", "AGENT", "Agent opérationnel"),
    AccountSpec("analyste", "ANALYST", "Analyste"),
    AccountSpec("auditeur", "AUDITOR", "Auditeur"),
)

DEMO_ORGANIZATIONS: tuple[OrganizationSpec, ...] = (
    OrganizationSpec(
        name="Organisme Démo A",
        short_name="DEMO-A",
        type="douane",
        domain="demo-a.rbi.test",
        letter="A",
        accounts=ACCOUNTS,
    ),
    OrganizationSpec(
        name="Organisme Démo B",
        short_name="DEMO-B",
        type="portuaire",
        domain="demo-b.rbi.test",
        letter="B",
        accounts=ACCOUNTS,
    ),
)


def _account_email(org: OrganizationSpec, account: AccountSpec) -> str:
    return f"{account.local_part}@{org.domain}"


@dataclass
class Summary:
    created: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = ["Données de démonstration (fictives) : résumé"]
        out.append(f"  créés : {len(self.created)}")
        out.extend(f"    + {item}" for item in self.created)
        out.append(f"  déjà présents : {len(self.present)}")
        out.extend(f"    = {item}" for item in self.present)
        out.append(
            "Activation des comptes : « Mot de passe oublié » sur l'écran de connexion, avec l'adresse"
        )
        out.append("du compte ; le lien est reçu dans la messagerie de développement (Mailpit).")
        return out


# --- Garde-fous -------------------------------------------------------------------------------------


def check_environment() -> None:
    """D6 : environnement explicitement autorisé, rôle applicatif uniquement (jamais le rôle propriétaire)."""
    environment = getattr(settings, "RBI_ENV", None)
    if environment not in ALLOWED_ENVIRONMENTS:
        raise SeedRefused(
            "Exécution refusée : RBI_ENV doit valoir explicitement « development » ou « test » "
            f"(valeur : {environment!r})."
        )
    if current_database_role() != settings.RBI_DB_APP_ROLE:
        raise SeedRefused(
            "Exécution refusée : rôle de base non applicatif (le rôle propriétaire est interdit)."
        )


def _find_user(email: str) -> User | None:
    """Recherche d'un compte par adresse exacte, avec le même périmètre ``auth_email`` que la connexion."""
    with db_scope(auth_email=email, current_user="", current_org="", platform=""):
        return User.objects.select_related("organization").filter(email=email).first()


def resolve_actor(actor_email: str) -> tuple[User, PlatformScope, PlatformScope]:
    """D4 : acteur existant, actif, sans organisme, détenant les deux permissions plateforme requises."""
    email = (actor_email or "").strip().lower()
    actor = _find_user(email) if email else None
    if actor is None:
        raise SeedRefused("Compte acteur introuvable : la commande ne crée jamais de compte administrateur.")
    try:
        with identity_scope(actor.pk):
            organizations = platform_scope(actor, purpose="seed_demo", permission=MANAGE_ORGANIZATIONS)
            institutional = platform_scope(
                actor, purpose="seed_demo", permission=INSTITUTIONAL_ADMINS_PERMISSION
            )
    except PlatformAccessDenied as exc:
        raise SeedRefused("Compte acteur non autorisé : Super Administrateur actif requis.") from exc
    return actor, organizations, institutional


# --- Lectures de planification (sans écriture) -------------------------------------------------------


@platform_operation(INSTITUTIONAL_ADMINS_PERMISSION)
def _org_role_codes(scope: PlatformScope, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Rôles d'organisme des comptes donnés (lecture autorisée par la politique RLS des affectations)."""
    result: dict[uuid.UUID, list[str]] = {}
    for assignment in UserRole.objects.filter(user_id__in=user_ids, scope="organization").select_related(
        "role"
    ):
        result.setdefault(assignment.user_id, []).append(assignment.role.code)
    return result


@dataclass
class OrgPlan:
    spec: OrganizationSpec
    existing: Organization | None
    missing_accounts: list[AccountSpec] = field(default_factory=list)
    admin_exists: bool = False


def _plan(scope_org: PlatformScope, scope_admin: PlatformScope) -> list[OrgPlan]:
    """Vérifie tout le lot avant la moindre écriture. Toute collision lève ``SeedRefused``."""
    all_orgs = list_organizations(scope_org)
    by_short = {o.short_name.lower(): o for o in all_orgs}
    by_name = {o.name.lower(): o for o in all_orgs}
    plans: list[OrgPlan] = []
    for spec in DEMO_ORGANIZATIONS:
        same_short = by_short.get(spec.short_name.lower())
        same_name = by_name.get(spec.name.lower())
        if same_short is not None and not same_short.is_demo:
            raise SeedRefused(
                f"Collision : l'organisme {spec.short_name} existe sans marquage de démonstration."
            )
        if same_name is not None and (same_short is None or same_name.pk != same_short.pk):
            raise SeedRefused(f"Collision : le nom « {spec.name} » est déjà utilisé par un autre organisme.")
        existing = same_short
        if existing is not None and (
            existing.name != spec.name or existing.status != Organization.Status.ACTIVE
        ):
            raise SeedRefused(
                f"Organisme {spec.short_name} présent dans un état inattendu : aucune modification effectuée."
            )
        plan = OrgPlan(spec=spec, existing=existing)
        emails = {_account_email(spec, a): a for a in spec.accounts}
        users: dict[str, User] = {}
        for email in emails:
            user = _find_user(email)
            if user is None:
                continue
            if user.organization_id is None or existing is None or user.organization_id != existing.pk:
                raise SeedRefused(f"Collision : le compte {email} existe hors du jeu de démonstration.")
            users[email] = user
        roles = _org_role_codes(scope_admin, [u.pk for u in users.values()]) if users else {}
        for email, account in emails.items():
            user = users.get(email)
            if user is None:
                plan.missing_accounts.append(account)
                continue
            if roles.get(user.pk, []) != [account.role]:
                raise SeedRefused(
                    f"Compte {email} présent avec des rôles différents : aucune modification effectuée."
                )
        plan.admin_exists = any(
            a.role == INSTITUTIONAL_ADMIN and _account_email(spec, a) in users for a in spec.accounts
        )
        if existing is not None and not plan.admin_exists:
            raise SeedRefused(
                f"Organisme {spec.short_name} sans administrateur institutionnel : aucune modification."
            )
        plans.append(plan)
    return plans


# --- Application (une seule transaction) -------------------------------------------------------------


def _apply(scope_org: PlatformScope, scope_admin: PlatformScope, plans: list[OrgPlan]) -> Summary:
    summary = Summary()
    today = dj_timezone.now().date()
    for plan in plans:
        spec = plan.spec
        if plan.existing is None:
            org = register_organization(
                scope_org,
                name=spec.name,
                short_name=spec.short_name,
                type=spec.type,
                country_code=DEMO_COUNTRY,
                timezone=DEMO_TIMEZONE,
                retention_days=DEMO_RETENTION_DAYS,
                is_demo=True,
            )
            summary.created.append(f"organisme {spec.short_name}")
            authorize_organization(
                scope_org,
                org,
                reference=spec.authorization_reference,
                scope_text=DEMO_SCOPE_TEXT,
                valid_from=today,
            )
            summary.created.append(f"autorisation {spec.authorization_reference}")
        else:
            org = plan.existing
            summary.present.append(f"organisme {spec.short_name}")

        admin_spec = spec.accounts[0]
        admin_email = _account_email(spec, admin_spec)
        admin: User | None
        if plan.existing is None:
            admin = create_institutional_admin(
                scope_admin,
                org,
                email=admin_email,
                first_name="Démo",
                last_name=f"{admin_spec.label} {spec.letter}",
            )
            summary.created.append(f"compte {admin_email} ({admin_spec.role})")
        else:
            # Planifié : l'administrateur existe déjà (sinon le lot a été refusé avant toute écriture).
            admin = _find_user(admin_email)
            summary.present.append(f"compte {admin_email} ({admin_spec.role})")
        if admin is None:
            raise SeedFailed("Échec : compte administrateur attendu introuvable (lot annulé).")

        if org.status == Organization.Status.AUTORISEE:
            org = activate_organization(scope_org, org)
            summary.created.append(f"activation {spec.short_name} (AUTORISEE → ACTIVE)")

        context = context_for_user(admin)
        for account in plan.missing_accounts:
            if account.role == INSTITUTIONAL_ADMIN:
                continue
            email = _account_email(spec, account)
            create_organization_user(
                admin,
                context,
                email=email,
                first_name="Démo",
                last_name=f"{account.label} {spec.letter}",
                roles=(account.role,),
            )
            summary.created.append(f"compte {email} ({account.role})")
        for account in spec.accounts:
            if account in plan.missing_accounts or account.role == INSTITUTIONAL_ADMIN:
                continue
            summary.present.append(f"compte {_account_email(spec, account)} ({account.role})")
    return summary


def seed_demo(actor_email: str) -> Summary:
    """Point d'entrée : garde-fous, planification sans écriture, puis application transactionnelle."""
    check_environment()
    _, scope_org, scope_admin = resolve_actor(actor_email)
    plans = _plan(scope_org, scope_admin)
    try:
        with transaction.atomic():
            return _apply(scope_org, scope_admin, plans)
    except SeedRefused:
        raise
    except Exception as exc:
        logger.exception("seed_demo : lot annulé")
        raise SeedFailed("Échec : aucune donnée de démonstration n'a été conservée (lot annulé).") from exc


__all__ = ["DEMO_ORGANIZATIONS", "SeedFailed", "SeedRefused", "Summary", "seed_demo"]
