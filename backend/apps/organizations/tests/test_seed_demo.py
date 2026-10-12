"""P2.11 — commande ``seed_demo`` : création, idempotence, refus, atomicité, audit, isolation (ADR 0013).

Les tests s'exécutent comme le service applicatif (``SET ROLE rbi_app``, RLS active). Les lectures de contrôle
passent par ``owner()`` uniquement pour inspecter la base, jamais pour exécuter la commande.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.integrity import chain_keys, verify_chain
from apps.audit.models import AuditLog
from apps.core.tests.api_support import signed_in
from apps.organizations import demo
from apps.organizations.models import Organization, OrganizationAuthorization
from apps.organizations.tenancy import context_for_user
from apps.users import services as users_services
from apps.users.models import User, UserRole
from apps.users.selectors import organization_user_rows
from conftest import create_user, grant_role, owner

pytestmark = pytest.mark.django_db

ROLES_BY_ACCOUNT = {
    "admin": "ORG_ADMIN",
    "superviseur": "SUPERVISOR",
    "agent": "AGENT",
    "analyste": "ANALYST",
    "auditeur": "AUDITOR",
}


def run_seed(actor_email: str) -> str:
    out = io.StringIO()
    call_command("seed_demo", "--actor-email", actor_email, stdout=out)
    return out.getvalue()


def counts() -> dict[str, int]:
    with owner():
        return {
            "organizations": Organization.objects.count(),
            "users": User.objects.count(),
            "user_roles": UserRole.objects.count(),
            "authorizations": OrganizationAuthorization.objects.count(),
        }


def snapshot() -> list[tuple[Any, ...]]:
    """Empreinte des lignes de démonstration et des comptes plateforme pour détecter toute modification."""
    with owner():
        orgs = [
            (o.short_name, o.name, o.status, o.is_demo, o.type, o.country_code)
            for o in Organization.objects.order_by("short_name")
        ]
        users = [
            (u.email, u.organization_id, u.is_active, u.is_demo, u.password)
            for u in User.objects.order_by("email")
        ]
    return orgs + users


@pytest.fixture
def actor(platform_admin: User) -> User:
    return platform_admin


def seed_once(actor: User, capture: Any) -> None:
    """Exécution de référence, appelée DANS le corps du test : le corps s'exécute sous le rôle applicatif,
    alors qu'une fixture s'exécute avant, sous le rôle propriétaire (que la commande refuse à juste titre)."""
    with capture(execute=True):
        run_seed(actor.email)


# --- Création -------------------------------------------------------------------------------------


def test_creates_two_demo_organisations_through_the_lifecycle(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        orgs = {o.short_name: o for o in Organization.objects.order_by("short_name")}
        assert set(orgs) == {"DEMO-A", "DEMO-B"}
        for short, org in orgs.items():
            assert org.is_demo is True
            assert org.status == Organization.Status.ACTIVE  # EN_ATTENTE → AUTORISEE → ACTIVE
            assert org.name == ("Organisme Démo A" if short == "DEMO-A" else "Organisme Démo B")
            authorization = OrganizationAuthorization.objects.get(organization=org)
            assert authorization.reference == f"DEMO-{short[-1]}-AUTH"
            assert authorization.valid_until is None


def test_five_accounts_per_organisation_one_per_institutional_role(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        for short, domain in (("DEMO-A", "demo-a.rbi.test"), ("DEMO-B", "demo-b.rbi.test")):
            org = Organization.objects.get(short_name=short)
            members = User.objects.filter(organization=org).order_by("email")
            assert sorted(m.email for m in members) == sorted(
                f"{local}@{domain}" for local in ROLES_BY_ACCOUNT
            )
            for member in members:
                local = member.email.split("@")[0]
                codes = list(
                    UserRole.objects.filter(user=member, scope="organization").values_list(
                        "role__code", flat=True
                    )
                )
                assert codes == [ROLES_BY_ACCOUNT[local]]  # un rôle exact, catalogue existant
                assert member.is_active is True
                assert member.has_usable_password() is False  # aucun mot de passe créé par la commande


def test_only_the_institutional_admin_is_designated_per_organisation(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        for org in Organization.objects.all():
            admins = UserRole.objects.filter(
                user__organization=org, scope="organization", role__code="ORG_ADMIN"
            ).count()
            assert admins == 1


def test_no_platform_account_is_created(actor: User, django_capture_on_commit_callbacks: Any) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        platform = User.objects.filter(organization__isnull=True).values_list("email", flat=True)
        assert list(platform) == [actor.email]


# --- Idempotence ----------------------------------------------------------------------------------


def test_second_run_creates_nothing_and_reports_presence(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    before = counts()
    with django_capture_on_commit_callbacks(execute=True):
        output = run_seed(actor.email)
    assert counts() == before
    assert "créés : 0" in output
    assert "= organisme DEMO-A" in output and "= organisme DEMO-B" in output


def test_second_run_does_not_modify_existing_rows(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    before = snapshot()
    run_seed(actor.email)
    assert snapshot() == before


# --- Refus : environnement, rôle, acteur -----------------------------------------------------------


@pytest.mark.parametrize("environment", ["production", "staging", "", None])
def test_refused_outside_development_and_test(settings: Any, actor: User, environment: Any) -> None:
    settings.RBI_ENV = environment
    before = counts()
    with pytest.raises(CommandError, match="RBI_ENV doit valoir explicitement"):
        run_seed(actor.email)
    assert counts() == before


def test_refused_under_the_owner_role(actor: User) -> None:
    before = counts()
    with owner(), pytest.raises(CommandError, match="rôle de base non applicatif"):
        run_seed(actor.email)
    assert counts() == before


def test_refused_for_an_unknown_actor(actor: User) -> None:
    before = counts()
    with pytest.raises(CommandError, match="Compte acteur introuvable"):
        run_seed("personne.inconnue@plateforme.rbi.test")
    assert counts() == before


def test_refused_for_a_platform_account_without_super_admin_role(
    platform_user_without_permission: User,
) -> None:
    before = counts()
    with pytest.raises(CommandError, match="Super Administrateur actif requis"):
        run_seed(platform_user_without_permission.email)
    assert counts() == before


def test_refused_for_an_organisation_account(admin_a: User) -> None:
    before = counts()
    with pytest.raises(CommandError, match="Super Administrateur actif requis"):
        run_seed(admin_a.email)
    assert counts() == before


def test_refused_for_an_inactive_super_admin(platform_admin: User) -> None:
    with owner():
        platform_admin.is_active = False
        platform_admin.save(update_fields=["is_active"])
    before = counts()
    with pytest.raises(CommandError, match="Super Administrateur actif requis"):
        run_seed(platform_admin.email)
    assert counts() == before


def test_the_command_never_creates_or_promotes_the_actor(actor: User) -> None:
    before = snapshot()
    with pytest.raises(CommandError):
        run_seed("nouveau.venu@plateforme.rbi.test")
    assert snapshot() == before


# --- Collisions : jamais d'écrasement -------------------------------------------------------------


def test_collision_with_an_unmarked_organisation_refuses_without_writes(
    make_organization: Any, actor: User
) -> None:
    make_organization(name="Organisme Démo A", short_name="DEMO-A", is_demo=False)
    before = snapshot()
    with pytest.raises(CommandError, match="sans marquage de démonstration"):
        run_seed(actor.email)
    assert snapshot() == before
    with owner():
        assert not Organization.objects.filter(short_name="DEMO-B").exists()


def test_collision_with_an_unmarked_account_refuses_without_writes(
    make_organization: Any, actor: User
) -> None:
    other = make_organization(name="Autre organisme", short_name="AUTRE-1", is_demo=False)
    # Le compte porte exactement le rôle attendu : seul le contrôle de collision peut le refuser.
    foreign = create_user("admin@demo-a.rbi.test", organization=other)
    grant_role(foreign, "ORG_ADMIN")
    before = snapshot()
    with pytest.raises(CommandError, match="hors du jeu de démonstration"):
        run_seed(actor.email)
    assert snapshot() == before


def test_existing_demo_accounts_with_changed_roles_are_never_modified(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        agent = User.objects.get(email="agent@demo-a.rbi.test")
    grant_role(agent, "ANALYST")  # rôle ajouté hors commande
    before = snapshot()
    with pytest.raises(CommandError, match="rôles différents"):
        run_seed(actor.email)
    assert snapshot() == before
    with owner():
        codes = sorted(UserRole.objects.filter(user=agent).values_list("role__code", flat=True))
    assert codes == ["AGENT", "ANALYST"]


# --- Atomicité et audit ---------------------------------------------------------------------------


def test_failure_in_the_middle_of_the_batch_leaves_nothing(
    monkeypatch: pytest.MonkeyPatch, actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    calls = {"n": 0}
    original = users_services.create_organization_user

    def failing(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("panne simulée")
        return original(*args, **kwargs)

    monkeypatch.setattr("apps.organizations.demo.create_organization_user", failing)
    before = counts()
    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(CommandError, match="aucune donnée de démonstration n'a été conservée"),
    ):
        run_seed(actor.email)
    assert counts() == before
    with owner():
        assert AuditLog.objects.filter(action="organization.register", outcome="success").count() == 0


def test_audit_attributes_each_creation_to_the_acting_actor(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        by_super_admin = set(AuditLog.objects.filter(actor_id=actor.pk).values_list("action", flat=True))
        admin_a = User.objects.get(email="admin@demo-a.rbi.test")
        by_admin_a = set(AuditLog.objects.filter(actor_id=admin_a.pk).values_list("action", flat=True))
    assert {"organization.register", "user.create_institutional_admin"} <= by_super_admin
    # Les comptes de l'organisme sont créés par son administrateur institutionnel, dans son contexte.
    assert "user.create" in by_admin_a


def test_audit_chain_remains_intact_after_the_seed(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    for key in chain_keys():
        with owner():
            report = verify_chain(key)
        assert report.intact, key


# --- Isolation et API existante --------------------------------------------------------------------


def test_organisation_admin_sees_only_its_own_accounts(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        admin_a = User.objects.get(email="admin@demo-a.rbi.test")
        user_b = User.objects.get(email="agent@demo-b.rbi.test")
    context = context_for_user(admin_a)
    rows = organization_user_rows(admin_a, context)
    assert sorted(r.user.email for r in rows) == sorted(
        f"{local}@demo-a.rbi.test" for local in ROLES_BY_ACCOUNT
    )
    with pytest.raises(User.DoesNotExist):
        organization_user_rows(admin_a, context, user_b.pk)


def test_api_serves_the_seeded_organisation_and_its_accounts(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        admin_a = User.objects.get(email="admin@demo-a.rbi.test")
    api = signed_in(admin_a)
    organization = api.get("/organization")
    assert organization.status_code == 200
    assert organization.json()["name"] == "Organisme Démo A"
    body = api.get("/users").content.decode()
    assert "@demo-a.rbi.test" in body and "@demo-b.rbi.test" not in body


# --- Absence de secrets -----------------------------------------------------------------------------


SECRET_MARKERS = ("token", "totp", "secret", "motdepasse", "password=")


def test_the_command_output_contains_no_secret(actor: User, django_capture_on_commit_callbacks: Any) -> None:
    """La sortie de la PREMIÈRE exécution est contrôlée seule : ce contrôle ne dépend pas de l'idempotence.
    Un refus de la seconde exécution est signalé comme tel (lacune CP-05 : l'échec passait par ce chemin)."""
    with django_capture_on_commit_callbacks(execute=True):
        first = run_seed(actor.email).lower()
    assert "créé" in first
    for marker in SECRET_MARKERS:
        assert marker not in first, marker
    try:
        second = run_seed(actor.email).lower()
    except CommandError as exc:
        pytest.fail(f"Seconde exécution refusée : idempotence rompue ({exc})")
    for marker in SECRET_MARKERS:
        assert marker not in second, marker


def test_the_seed_module_hardcodes_no_credential() -> None:
    source = Path(demo.__file__).read_text(encoding="utf-8")
    assert not re.search(r"set_password|password\s*=|secret\s*=|token\s*=", source)


def test_application_filter_isolates_without_rls(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    """Défense en profondeur : la requête s'exécute en rôle propriétaire (RLS contourné). Le filtre applicatif
    de l'organisme du contexte doit à lui seul écarter les comptes de l'organisme B."""
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        admin_a = User.objects.get(email="admin@demo-a.rbi.test")
        context = context_for_user(admin_a)
        rows = organization_user_rows(admin_a, context)
    assert sorted(r.user.email for r in rows) == sorted(
        f"{local}@demo-a.rbi.test" for local in ROLES_BY_ACCOUNT
    )


# --- Marquage des comptes (User.is_demo, §26) -----------------------------------------------------


def test_seeded_accounts_are_marked_and_only_in_demo_organisations(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        marked = list(User.objects.filter(is_demo=True).select_related("organization"))
        unmarked_platform = User.objects.filter(organization__isnull=True, is_demo=True).count()
    assert len(marked) == 10
    assert all(u.organization is not None and u.organization.is_demo for u in marked)
    assert unmarked_platform == 0
    with owner():
        assert User.objects.get(pk=actor.pk).is_demo is False


def test_an_unmarked_account_of_the_set_refuses_without_writes(
    actor: User, django_capture_on_commit_callbacks: Any
) -> None:
    seed_once(actor, django_capture_on_commit_callbacks)
    with owner():
        User.objects.filter(email="agent@demo-a.rbi.test").update(is_demo=False)
    before = snapshot()
    with pytest.raises(CommandError, match="hors du jeu"):
        run_seed(actor.email)
    assert snapshot() == before


def test_services_refuse_a_demo_account_outside_a_demo_organisation(
    admin_a: User, org_a: Organization
) -> None:
    from apps.organizations.exceptions import InvalidTransition

    with owner():
        Organization.objects.filter(pk=org_a.pk).update(is_demo=False)  # organisme ordinaire
    with pytest.raises(InvalidTransition):
        users_services.create_organization_user(
            admin_a, context_for_user(admin_a), email="x@demo-a.rbi.test", roles=("AGENT",), is_demo=True
        )
    with owner():
        assert not User.objects.filter(email="x@demo-a.rbi.test").exists()


def test_an_account_created_through_the_api_is_never_marked(admin_a: User) -> None:
    api = signed_in(admin_a)
    response = api.post("/users", {"email": "nouveau@demo-a.rbi.test", "roles": ["AGENT"]})
    assert response.status_code == 201, response.content[:200]
    assert "is_demo" not in response.json()  # contrat P1 inchangé : le marqueur n'est pas exposé
    with owner():
        assert User.objects.get(email="nouveau@demo-a.rbi.test").is_demo is False
