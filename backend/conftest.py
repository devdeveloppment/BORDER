"""Fixtures partagées : organismes et comptes fictifs (aucune institution réelle).

P2.6 — rôle PostgreSQL des tests :
- la connexion de test appartient au rôle propriétaire (création et migration de ``test_rbi``) ;
- le CORPS de chaque test ``django_db`` s'exécute en tant que rôle applicatif (``SET ROLE rbi_app``), donc
  soumis au RLS exactement comme l'API et le worker ; toutes les autres fixtures du test sont résolues avant ;
- la préparation et la simulation d'états passent explicitement par ``owner()`` (rôle propriétaire, hors
  RLS) ;
- exceptions : tests transactionnels (migrations) et tests marqués ``@pytest.mark.db_owner``.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from django.db import connection

from apps.organizations.models import Organization, OrganizationAuthorization
from apps.users.models import Role, User, UserRole

OrganizationFactory = Callable[..., Organization]
APP_ROLE = os.environ.get("RBI_DB_APP_USER", "rbi_app")


def _current_role() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        row = cursor.fetchone()
    return str(row[0]) if row else ""


@contextmanager
def owner() -> Iterator[None]:
    """Repasse temporairement au rôle propriétaire (préparation de données, simulation d'un état)."""
    was_app = _current_role() == APP_ROLE
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
    try:
        yield
    finally:
        if was_app:
            with connection.cursor() as cursor:
                cursor.execute("SET ROLE %s" % connection.ops.quote_name(APP_ROLE))  # noqa: UP031


@pytest.fixture(autouse=True)
def _isolated_rate_limits() -> Iterator[None]:
    """Compteurs de limitation (P2.5, et DRF en P2.8 : par adresse et par compte) remis à zéro avant chaque
    test : tous les tests partagent l'adresse 127.0.0.1. Cache Redis des tests (base 4), distinct du
    développement."""
    from django.core.cache import caches

    caches["default"].clear()
    yield


@pytest.fixture(autouse=True)
def _run_test_body_as_application_role(request: pytest.FixtureRequest) -> Iterator[None]:
    marker = request.node.get_closest_marker("django_db")
    transactional = bool(marker and (marker.kwargs.get("transaction") or (marker.args and marker.args[0])))
    if marker is None or transactional or request.node.get_closest_marker("db_owner"):
        yield
        return
    for name in request.fixturenames:  # données préparées en propriétaire, avant le changement de rôle
        if name != "_run_test_body_as_application_role":
            request.getfixturevalue(name)
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE %s" % connection.ops.quote_name(APP_ROLE))  # noqa: UP031
    yield
    try:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
    except Exception:  # noqa: S110 - transaction de test déjà annulée : le rôle l'est aussi
        pass


@pytest.fixture
def make_organization(db: None) -> OrganizationFactory:
    """Crée un organisme directement en base (préparation de test, hors services du cycle de vie)."""
    counter = {"n": 0}

    def factory(**overrides: Any) -> Organization:
        counter["n"] += 1
        n = counter["n"]
        values: dict[str, Any] = {
            "name": f"Organisme Démo {n}",
            "short_name": f"DEMO-{n}",
            "type": Organization.Type.DOUANE,
            "status": Organization.Status.ACTIVE,
            "country_code": "TG",
            "timezone": "Africa/Lome",
            "retention_days": 365,
            "is_demo": True,
        }
        values.update(overrides)
        with owner():
            return Organization.objects.create(**values)

    return factory


@pytest.fixture
def org_a(make_organization: OrganizationFactory) -> Organization:
    return make_organization(name="Organisme Démo A", short_name="DEMO-A")


@pytest.fixture
def org_b(make_organization: OrganizationFactory) -> Organization:
    return make_organization(name="Organisme Démo B", short_name="DEMO-B", type=Organization.Type.PORTUAIRE)


def create_user(email: str, organization: Organization | None = None, **extra: Any) -> User:
    """Compte de test créé en propriétaire (mot de passe fictif par défaut)."""
    extra.setdefault("password", "Fictif-2026-mdp!")
    with owner():
        return User.objects.create_user(email=email, organization=organization, **extra)


def grant_role(user: User, code: str) -> UserRole:
    """Affectation directe pour préparer un test (hors services, donc sans les règles d'élévation)."""
    scope = "platform" if user.organization_id is None else "organization"
    with owner():
        role = Role.objects.get(code=code, scope=scope, organization__isnull=True)
        return UserRole.objects.create(
            user=user,
            role=role,
            scope=scope,
            organization_id=user.organization_id if scope == "organization" else None,
        )


@pytest.fixture
def platform_admin(db: None) -> User:
    """Compte plateforme (sans organisme) doté du rôle SUPER_ADMIN."""
    user = create_user("super.admin@plateforme.rbi.test", password="Fictif-Plateforme-2026!")
    grant_role(user, "SUPER_ADMIN")
    return user


@pytest.fixture
def platform_user_without_permission(db: None) -> User:
    return create_user("auditeur.plateforme@plateforme.rbi.test")


@pytest.fixture
def user_a(org_a: Organization) -> User:
    return create_user("agent@demo-a.rbi.test", org_a)


@pytest.fixture
def admin_a(org_a: Organization) -> User:
    user = create_user("admin@demo-a.rbi.test", org_a)
    grant_role(user, "ORG_ADMIN")
    return user


@pytest.fixture
def admin_b(org_b: Organization) -> User:
    user = create_user("admin@demo-b.rbi.test", org_b)
    grant_role(user, "ORG_ADMIN")
    return user


@pytest.fixture
def user_b(org_b: Organization) -> User:
    return create_user("agent@demo-b.rbi.test", org_b)


def add_authorization(
    organization: Organization, granted_by: User, **overrides: Any
) -> OrganizationAuthorization:
    values: dict[str, Any] = {
        "reference": "CONV-DEMO-2026-001",
        "scope": "Périmètre fictif de démonstration",
        "valid_from": datetime.date(2026, 1, 1),
        "valid_until": None,
    }
    values.update(overrides)
    with owner():
        return OrganizationAuthorization.objects.create(
            organization=organization, granted_by=granted_by, **values
        )
