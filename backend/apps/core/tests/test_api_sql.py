"""Fonctions SQL de lecture de l'API (P2.8), éprouvées en SQL direct sous ``rbi_app`` (corps de test)."""

from __future__ import annotations

from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.users.models import User
from conftest import grant_role, owner

pytestmark = pytest.mark.django_db


def scope(org: object = "", user: object = "", platform: str = "") -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.current_org', %s, true), set_config('app.current_user', %s, true), "
            "set_config('app.platform', %s, true)",
            [str(org or ""), str(user or ""), platform],
        )


def rows(sql: str) -> list[Any]:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return list(cursor.fetchall())


def refused(sql: str) -> str:
    with pytest.raises(DatabaseError) as excinfo, transaction.atomic():
        rows(sql)
    return str(excinfo.value)


@pytest.fixture
def enrolled(user_a: User, user_b: User) -> None:
    with owner():
        TOTPDevice.objects.create(user=user_a, name="totp", confirmed=True)
        TOTPDevice.objects.create(user=user_b, name="totp", confirmed=True)


def test_mfa_status_requires_users_view_in_the_context_organization(
    enrolled: None, admin_a: User, user_a: User, user_b: User
) -> None:
    assert "lecture du statut MFA refusée" in refused("SELECT * FROM rbi_org_mfa_enabled_users()")
    grant_role(user_a, "AGENT")
    scope(org=user_a.organization_id, user=user_a.pk)
    assert "refusée" in refused("SELECT * FROM rbi_org_mfa_enabled_users()")
    scope(org=user_b.organization_id, user=admin_a.pk)  # contexte falsifié : administrateur de A, organisme B
    assert "refusée" in refused("SELECT * FROM rbi_org_mfa_enabled_users()")
    scope(org=admin_a.organization_id, user=admin_a.pk)
    assert rows("SELECT * FROM rbi_org_mfa_enabled_users()") == [(user_a.pk,)]  # jamais un compte de B
    assert rows("SELECT count(*) FROM otp_totp_totpdevice") == [(0,)]  # appareils toujours illisibles


def test_account_counts_require_the_platform_operation(
    platform_admin: User, admin_a: User, user_a: User, admin_b: User
) -> None:
    assert "statistique plateforme refusée" in refused("SELECT * FROM rbi_platform_org_user_counts()")
    scope(user=platform_admin.pk)
    assert "refusée" in refused("SELECT * FROM rbi_platform_org_user_counts()")
    scope(user=admin_a.pk, platform="platform.organizations")  # compte d'organisme, variable falsifiée
    assert "refusée" in refused("SELECT * FROM rbi_platform_org_user_counts()")
    scope(user=platform_admin.pk, platform="platform.organizations")
    counts = dict(rows("SELECT * FROM rbi_platform_org_user_counts()"))
    assert counts[admin_a.organization_id] == 2 and counts[admin_b.organization_id] == 1
    assert rows("SELECT count(*) FROM users_user WHERE organization_id IS NOT NULL") == [
        (0,)
    ]  # comptes illisibles
