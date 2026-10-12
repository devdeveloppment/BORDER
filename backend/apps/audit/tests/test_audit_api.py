"""API du journal d'audit (P2.8) : consultation, filtres, pagination, export, intégrité, isolation,
traçabilité."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

import pytest
from django.db import connection

from apps.audit import selectors
from apps.audit.models import AuditLog
from apps.audit.services import record_event
from apps.authentication.tests.support import PASSWORD, Api, enroll, make_member
from apps.core.tests.api_support import signed_in
from apps.organizations.models import Organization
from apps.organizations.tenancy import TenantContext, tenant_context
from apps.users.models import User
from conftest import create_user, grant_role, owner

pytestmark = pytest.mark.django_db

P1_AUDIT_ENTRY = {
    "id",
    "created_at",
    "actor",
    "action",
    "object_type",
    "object_repr",
    "ip_address",
    "result",
    "old_value",
    "new_value",
    "hash",
}
P1_AUDIT_PAGE = {"count", "page", "page_size", "results", "chain_integrity"}


@pytest.fixture
def journal(
    admin_a: User, admin_b: User, user_a: User, org_a: Organization, org_b: Organization
) -> dict[str, Any]:
    """Entrées fictives dans A et dans B, et une entrée de portée plateforme."""
    with tenant_context(TenantContext(org_a.pk, "user", admin_a.pk)):
        record_event(
            "user.create",
            outcome="success",
            actor_id=admin_a.pk,
            organization_id=org_a.pk,
            object_type="user",
            object_id=user_a.pk,
            new_value={"roles": ["AGENT"]},
        )
        record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
        record_event(
            "user.set_active",
            outcome="denied",
            actor_id=admin_a.pk,
            organization_id=org_a.pk,
            details={"reason": '=HYPERLINK("http://exemple.invalid")'},
        )
    with tenant_context(TenantContext(org_b.pk, "user", admin_b.pk)):
        record_event("user.create", outcome="success", actor_id=admin_b.pk, organization_id=org_b.pk)
    record_event("auth.login", outcome="failure", actor_id=None, details={"reason": "invalid_credentials"})
    return {"org_a": org_a, "org_b": org_b}


def audit_reads(user: User) -> int:
    with owner():
        return AuditLog.objects.filter(actor_id=user.pk, action="audit.read").count()


def test_real_login_with_mfa_then_consultation(org_a: Organization) -> None:
    """Bout en bout réel : mot de passe, enrôlement TOTP, session, CSRF, RBAC, RLS — Auditeur de
    l'organisme."""
    auditor = make_member(org_a, "AUDITOR", "auditeur.reel@demo-a.rbi.test")
    api = Api()
    enroll(api, auditor)
    response = api.get("/audit-logs?action=auth")
    assert response.status_code == 200, response.content
    actions = {entry["action"] for entry in response.json()["results"]}
    assert {"auth.login", "auth.mfa.enroll.start", "auth.mfa.verify", "auth.session.open"} <= actions
    assert PASSWORD not in response.content.decode()


def test_page_follows_p1_contract_and_own_organization_only(journal: dict[str, Any], admin_a: User) -> None:
    response = signed_in(admin_a).get("/audit-logs")
    body = response.json()
    assert response.status_code == 200 and set(body) == P1_AUDIT_PAGE
    assert body["chain_integrity"] == "non_verifiee" and (body["page"], body["page_size"]) == (1, 50)
    assert all(set(entry) >= P1_AUDIT_ENTRY for entry in body["results"])
    assert {entry["organization_id"] for entry in body["results"]} == {str(journal["org_a"].pk)}
    assert str(journal["org_b"].pk) not in response.content.decode()
    by_action = {e["action"]: e for e in body["results"]}
    created = by_action["user.create"]
    assert (created["actor"], created["result"], created["outcome"]) == (admin_a.email, "succes", "success")
    assert created["object_repr"].startswith("user:")
    assert by_action["user.set_active"]["result"] == "echec"


def test_foreign_actor_filter_returns_nothing(journal: dict[str, Any], admin_a: User, admin_b: User) -> None:
    body = signed_in(admin_a).get(f"/audit-logs?actor_id={admin_b.pk}").json()
    assert body["count"] == 0 and body["results"] == []


def test_organization_parameter_is_refused_not_trusted(journal: dict[str, Any], admin_a: User) -> None:
    response = signed_in(admin_a).get(f"/audit-logs?organization_id={journal['org_b'].pk}")
    assert response.status_code == 400
    assert response.json()["errors"] == {"organization_id": ["Paramètre non pris en charge."]}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("action=auth", {"auth.reauthenticate"}),
        ("action=user.create", {"user.create"}),
        ("action=user", {"user.create", "user.set_active"}),
        ("outcome=denied", {"user.set_active"}),
        ("object_type=user", {"user.create"}),
        ("date_from=2000-01-01&action=user.create", {"user.create"}),
        ("date_to=2000-01-01", set()),
    ],
)
def test_filters(journal: dict[str, Any], admin_a: User, query: str, expected: set[str]) -> None:
    body = signed_in(admin_a).get(f"/audit-logs?{query}").json()
    assert {e["action"] for e in body["results"] if e["action"] != "audit.read"} == expected


def test_ordering_is_deterministic_and_pagination_bounded(journal: dict[str, Any], admin_a: User) -> None:
    api = signed_in(admin_a)
    newest = [e["id"] for e in api.get("/audit-logs?action=user").json()["results"]]
    oldest = [e["id"] for e in api.get("/audit-logs?action=user&ordering=id").json()["results"]]
    assert newest == sorted(newest, reverse=True) and oldest == sorted(oldest) == sorted(newest)
    first = api.get("/audit-logs?action=user&page_size=1").json()
    second = api.get("/audit-logs?action=user&page_size=1&page=2").json()
    assert first["count"] == second["count"] == 2 and first["results"][0]["id"] != second["results"][0]["id"]
    assert api.get("/audit-logs?action=user&page=50").json()["results"] == []


@pytest.mark.parametrize(
    "query",
    [
        "page_size=101",
        "page_size=0",
        "page=0",
        "page=101&page_size=100",
        "action=AUTH",
        "action=auth.%25",
        "outcome=ok",
        "actor_id=pas-un-uuid",
        "object_type=password",
        "date_from=2026-13-01",
        "date_from=2026-02-01&date_to=2026-01-01",
        "ordering=created_at",
        "unknown=1",
    ],
)
def test_invalid_parameters_are_refused(journal: dict[str, Any], admin_a: User, query: str) -> None:
    response = signed_in(admin_a).get(f"/audit-logs?{query}")
    assert response.status_code == 400, query
    assert response.json()["title"] == "Requête invalide"


def test_each_consultation_is_audited_once_without_loop(journal: dict[str, Any], admin_a: User) -> None:
    api = signed_in(admin_a)
    before = audit_reads(admin_a)
    api.get("/audit-logs?outcome=denied")
    api.get("/audit-logs?outcome=denied")
    assert audit_reads(admin_a) == before + 2
    with owner():
        event = AuditLog.objects.filter(actor_id=admin_a.pk, action="audit.read").latest("id")
    assert event.metadata["outcome_filter"] == "denied" and event.metadata["count"] == 1


def test_journal_is_read_only_over_http(journal: dict[str, Any], admin_a: User) -> None:
    api = signed_in(admin_a)
    with owner():
        entry_id = AuditLog.objects.filter(organization_id=journal["org_a"].pk).latest("id").pk
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in ("/audit-logs", f"/audit-logs/{entry_id}", "/audit-logs/export"):
            assert api.request(method, path, {} if method != "DELETE" else None).status_code in (404, 405), (
                method,
                path,
            )
    with owner():
        assert AuditLog.objects.filter(pk=entry_id).exists()


def test_roles_without_audit_permission_are_refused(journal: dict[str, Any], org_a: Organization) -> None:
    for role in ("AGENT", "ANALYST", "SUPERVISOR"):
        member = create_user(f"{role.lower()}.audit@demo-a.rbi.test", org_a)
        grant_role(member, role)
        api = signed_in(member)
        for path in ("/audit-logs", "/audit-logs/export", "/audit-logs/integrity"):
            assert api.get(path).status_code == 403, (role, path)


def test_export_is_csv_bounded_neutralized_and_audited(journal: dict[str, Any], admin_a: User) -> None:
    response = signed_in(admin_a).get("/audit-logs/export?action=user")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"].startswith('attachment; filename="rbi-audit-organisme-')
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
    assert {row["action"] for row in rows} == {"user.create", "user.set_active"}
    assert {row["organization_id"] for row in rows} == {str(journal["org_a"].pk)}
    denied = next(row for row in rows if row["action"] == "user.set_active")
    assert denied["details"].startswith("{")  # objet JSON : le « = » n'est jamais en tête de cellule
    with owner():
        event = AuditLog.objects.filter(actor_id=admin_a.pk, action="audit.export").latest("id")
    assert (event.outcome, event.metadata["rows"], event.metadata["action_filter"]) == ("success", 2, "user")


def test_formula_in_a_cell_is_neutralized() -> None:
    from apps.audit.api import _cell

    assert (
        _cell("=1+1") == "'=1+1" and _cell("@SUM") == "'@SUM" and _cell("-2") == "'-2" and _cell("ok") == "ok"
    )


def test_export_over_the_limit_is_refused_and_audited(
    journal: dict[str, Any], admin_a: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selectors, "EXPORT_MAX_ROWS", 1)
    response = signed_in(admin_a).get("/audit-logs/export?action=user")
    assert (
        response.status_code == 400
        and "limité à 1 lignes" in response.json()["errors"]["non_field_errors"][0]
    )
    with owner():
        event = AuditLog.objects.filter(actor_id=admin_a.pk, action="audit.export").latest("id")
    assert (event.outcome, event.metadata["reason"], event.metadata["count"]) == (
        "denied",
        "too_many_rows",
        2,
    )


def test_integrity_endpoint_detects_tampering(journal: dict[str, Any], admin_a: User) -> None:
    api = signed_in(admin_a)
    sound = api.get("/audit-logs/integrity").json()
    assert sound["chain_integrity"] == "valide" and sound["chain"] == str(journal["org_a"].pk)
    with (
        owner(),
        connection.cursor() as cursor,
    ):  # altération par un administrateur de la base (annulée ensuite)
        cursor.execute("ALTER TABLE audit_auditlog DISABLE TRIGGER rbi_audit_immutable")
        cursor.execute(
            "UPDATE audit_auditlog SET outcome = 'success' WHERE organization_id = %s AND action = %s",
            [journal["org_a"].pk, "user.set_active"],
        )
        cursor.execute("ALTER TABLE audit_auditlog ENABLE TRIGGER rbi_audit_immutable")
    broken = api.get("/audit-logs/integrity").json()
    assert broken["chain_integrity"] == "rompue" and broken["errors"]


def test_platform_journal(journal: dict[str, Any], platform_admin: User, admin_a: User) -> None:
    auditor = create_user("auditeur.api@plateforme.rbi.test")
    grant_role(auditor, "AUDITOR")
    for user in (platform_admin, auditor):
        body = signed_in(user).get("/platform/audit-logs").json()
        assert body["results"] and {e["scope"] for e in body["results"]} == {"platform"}
        assert all(e["action"] not in ("auth.reauthenticate", "user.set_active") for e in body["results"])
    assert signed_in(auditor).get("/platform/audit-logs/integrity").json()["chain_integrity"] == "valide"
    export = signed_in(auditor).get("/platform/audit-logs/export?action=auth.login")
    assert export.status_code == 200 and "auth.login" in export.content.decode()
    assert signed_in(admin_a).get("/platform/audit-logs").status_code == 403


def test_actor_labels_never_reveal_accounts_outside_the_scope(
    journal: dict[str, Any], platform_admin: User, admin_a: User, org_a: Organization
) -> None:
    """Une opération plateforme sur l'organisme A apparaît dans le journal de A, mais l'adresse du compte
    plateforme n'y est pas révélée (RLS : comptes de son organisme seulement)."""
    api = signed_in(platform_admin)
    api.patch(f"/platform/organizations/{org_a.pk}", {"retention_days": 400})
    entries = signed_in(admin_a).get("/audit-logs?action=organization.update").json()["results"]
    assert entries and entries[0]["actor"] == f"Compte {str(platform_admin.pk)[:8]}"
    assert platform_admin.email not in str(entries)


def test_no_entry_can_be_fetched_by_guessing_identifiers(journal: dict[str, Any], admin_a: User) -> None:
    with owner():
        foreign = AuditLog.objects.filter(organization_id=journal["org_b"].pk).latest("id").pk
    assert signed_in(admin_a).get(f"/audit-logs/{foreign}").status_code == 404
    body = signed_in(admin_a).get(f"/audit-logs?object_id={uuid.uuid4()}").json()
    assert body["count"] == 0


def test_application_filter_isolates_the_journal_even_without_rls(
    journal: dict[str, Any], admin_a: User
) -> None:
    """Défense en profondeur : requêtes exécutées en rôle propriétaire (RLS contourné) — le filtre applicatif
    sur l'organisme du contexte suffit à lui seul (liste, export)."""
    api = signed_in(admin_a)
    with owner():
        page = api.get("/audit-logs?page_size=100").json()
        export = api.get("/audit-logs/export").content.decode()
    assert {e["organization_id"] for e in page["results"]} == {str(journal["org_a"].pk)}
    assert str(journal["org_b"].pk) not in export
