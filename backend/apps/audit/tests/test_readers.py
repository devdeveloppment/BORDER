"""Consultation du journal (écran 22) : chemins dédiés, autorisés, isolés et eux-mêmes tracés (P2.7)."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditLog
from apps.audit.selectors import (
    list_organization_events,
    list_platform_events,
    verify_organization_chain,
    verify_platform_chain,
)
from apps.audit.services import record_event
from apps.organizations.exceptions import PlatformAccessDenied
from apps.organizations.models import Organization
from apps.organizations.platform import platform_scope
from apps.organizations.tenancy import TenantContext, context_for_user
from apps.users.models import User
from apps.users.rbac import PermissionDeniedError
from conftest import create_user, grant_role, owner

pytestmark = pytest.mark.django_db


@pytest.fixture
def activity(admin_a: User, admin_b: User, org_a: Organization, org_b: Organization) -> None:
    """Une entrée dans chaque organisme et une entrée plateforme."""
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_b.pk, organization_id=org_b.pk)
    record_event("auth.login", outcome="failure", actor_id=None, details={"reason": "invalid_credentials"})


def test_organization_admin_reads_only_its_organization(
    activity: None, admin_a: User, admin_b: User, org_a: Organization
) -> None:
    rows = list_organization_events(admin_a, context_for_user(admin_a))
    assert rows and {row.organization_id for row in rows} == {org_a.pk}
    assert admin_b.pk not in {row.actor_id for row in rows}


def test_organization_auditor_can_read(activity: None, org_a: Organization) -> None:
    auditor = create_user("auditeur@demo-a.rbi.test", org_a)
    grant_role(auditor, "AUDITOR")
    assert list_organization_events(auditor, context_for_user(auditor))


@pytest.mark.parametrize("role", ["AGENT", "ANALYST", "SUPERVISOR"])
def test_roles_without_audit_permission_are_refused_and_recorded(
    activity: None, org_a: Organization, role: str
) -> None:
    member = create_user(f"{role.lower()}@demo-a.rbi.test", org_a)
    grant_role(member, role)
    with pytest.raises(PermissionDeniedError):
        list_organization_events(member, context_for_user(member))
    with owner():
        event = AuditLog.objects.filter(actor_id=member.pk).latest("id")
    assert (event.action, event.outcome, event.metadata["permission"]) == (
        "rbac.check",
        "denied",
        "audit.view",
    )


def test_foreign_context_is_refused(activity: None, admin_a: User, org_b: Organization) -> None:
    with pytest.raises(PermissionDeniedError):
        list_organization_events(admin_a, TenantContext(org_b.pk, "user", admin_a.pk))


def test_reading_is_itself_recorded(activity: None, admin_a: User, org_a: Organization) -> None:
    rows = list_organization_events(admin_a, context_for_user(admin_a), action="auth.reauthenticate")
    with owner():
        event = AuditLog.objects.filter(action="audit.read", actor_id=admin_a.pk).latest("id")
    assert event.organization_id == org_a.pk
    assert event.metadata == {"count": len(rows), "action_filter": "auth.reauthenticate", "before_id": None}


def test_platform_auditor_reads_platform_entries_only(activity: None, org_a: Organization) -> None:
    auditor = create_user("auditeur@plateforme.rbi.test")
    grant_role(auditor, "AUDITOR")
    rows = list_platform_events(platform_scope(auditor, purpose="audit", permission="platform.audit"))
    assert rows and {row.scope for row in rows} == {"platform"}
    assert all(
        row.action != "auth.reauthenticate" for row in rows
    )  # activité interne des organismes : jamais


def test_platform_reading_requires_platform_audit_scope(
    activity: None, platform_admin: User, admin_a: User
) -> None:
    with pytest.raises(PlatformAccessDenied):
        list_platform_events(
            platform_scope(platform_admin, purpose="gestion")
        )  # scope platform.organizations
    with pytest.raises(PlatformAccessDenied):
        platform_scope(admin_a, purpose="audit", permission="platform.audit")


def test_chain_verification_for_organization_and_platform(
    activity: None, admin_a: User, platform_admin: User, org_a: Organization
) -> None:
    report = verify_organization_chain(admin_a, context_for_user(admin_a))
    assert report.intact and report.checked >= 1 and report.chain == str(org_a.pk)
    platform_report = verify_platform_chain(
        platform_scope(platform_admin, purpose="audit", permission="platform.audit")
    )
    assert platform_report.intact and platform_report.checked >= 1
    with owner():
        assert AuditLog.objects.filter(action="audit.verify", actor_id=admin_a.pk, outcome="success").exists()
