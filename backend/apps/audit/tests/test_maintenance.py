"""Maintenance du journal : vérification transversale (rôle de maintenance) et retour arrière protégé
(P2.7)."""

from __future__ import annotations

import io
import json

import pytest
from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection

from apps.audit.models import AuditLog
from apps.audit.services import record_event
from apps.core.maintenance import MaintenanceRoleRequired
from apps.organizations.models import Organization
from apps.users.models import User
from conftest import owner


@pytest.mark.django_db
def test_cross_organization_verification_is_refused_to_the_application_role() -> None:
    with pytest.raises(MaintenanceRoleRequired):
        call_command("audit_verify", stdout=io.StringIO())


@pytest.mark.django_db
@pytest.mark.db_owner
def test_audit_verify_reports_every_chain_and_is_traced(admin_a: User, org_a: Organization) -> None:
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    record_event("auth.login", outcome="failure", actor_id=None)
    out = io.StringIO()
    call_command("audit_verify", stdout=out)
    reports = {r["chain"]: r for r in map(json.loads, out.getvalue().splitlines())}
    assert reports[str(org_a.pk)]["intact"] is True and len(reports[str(org_a.pk)]["head_hash"]) == 64
    assert "platform" in reports
    traced = AuditLog.objects.filter(action="audit.verify", object_id=str(org_a.pk)).latest("id")
    assert (traced.actor_type, traced.metadata["channel"]) == ("system", "maintenance")


@pytest.mark.django_db
@pytest.mark.db_owner
def test_audit_verify_fails_on_tampering(admin_a: User, org_a: Organization) -> None:
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    with (
        connection.cursor() as cursor
    ):  # altération par un administrateur de la base (annulée en fin de test)
        cursor.execute("ALTER TABLE audit_auditlog DISABLE TRIGGER rbi_audit_immutable")
        cursor.execute("UPDATE audit_auditlog SET outcome = 'success' WHERE organization_id = %s", [org_a.pk])
    with pytest.raises(CommandError, match=str(org_a.pk)):
        call_command("audit_verify", stdout=io.StringIO())


@pytest.mark.django_db(transaction=True)
def test_reverting_the_audit_migration_is_refused_while_entries_exist() -> None:
    """Le retour arrière détruirait le journal : refusé sans décision explicite du propriétaire
    (SET rbi.audit_allow_drop = 'on'), que seul le test de réversibilité complète utilise."""
    record_event("audit.verify", outcome="success", actor_id=None, system=True)
    with pytest.raises(DatabaseError, match="retour arrière refusé"):
        call_command("migrate", "audit", "zero", verbosity=0)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('public.audit_auditlog') IS NOT NULL, count(*) > 0 FROM audit_auditlog"
        )
        assert cursor.fetchone() == (True, True)


@pytest.mark.django_db
def test_owner_helper_is_not_needed_for_reading_in_owner_tests() -> None:
    """Garde-fou du harnais : dans un test ordinaire, le corps s'exécute bien sous le rôle applicatif, et la
    lecture du journal sans permission n'y renvoie rien."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, count(*) FROM audit_auditlog")
        role, count = cursor.fetchone()
    with owner(), connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone() != (role,)
    assert count == 0
