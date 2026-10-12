"""Statut de démonstration enregistré dans les événements plateforme, et mention de l'export du journal
plateforme (P2.11, §26).

Le statut est écrit dans les métadonnées (clé ``demo``) par l'opération plateforme qui a l'organisme dans son
périmètre, au moment de l'événement ; l'export le relit dans les seules entrées que l'auditeur peut lire.
Aucune fonction SQL, aucun privilège, aucune politique RLS ne sont ajoutés.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import logging
from typing import Any

import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext

from apps.audit import selectors
from apps.audit.api import CSV_COLUMNS, DEMO_MENTION, UNDETERMINED_MENTION, _cell, _csv_response
from apps.audit.integrity import PLATFORM_CHAIN, verify_chain
from apps.audit.models import AuditLog
from apps.audit.services import record_event
from apps.core.db_scope import db_scope
from apps.core.tests.api_support import ApiClient, signed_in
from apps.organizations import services
from apps.organizations.exceptions import InvalidTransition
from apps.organizations.models import Organization
from apps.organizations.platform import platform_scope
from apps.users.models import User
from apps.users.services import create_institutional_admin
from conftest import create_user, grant_role, owner

pytestmark = pytest.mark.django_db

EXPORT = "/platform/audit-logs/export"
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")

# Les neuf appels ``record_event`` de portée plateforme qui visent un organisme (action, résultat, motif).
EXPECTED_EVENTS = {
    ("organization.register", "success", None),
    ("organization.update", "success", None),
    ("organization.transition", "denied", None),
    ("organization.transition", "success", None),
    ("organization.authorization.add", "success", None),
    ("organization.activate", "denied", "no_institutional_admin"),
    ("organization.activate", "denied", "no_valid_authorization"),
    ("user.create_institutional_admin", "success", None),
    ("user.create_institutional_admin", "failure", "email_unavailable"),
}

# Fonctions SECURITY DEFINER exécutables par le rôle applicatif avant P2.11 : la fonctionnalité n'en ajoute
# aucune.
DEFINER_FUNCTIONS_FOR_APP = {
    "rbi_admin_reset_mfa",
    "rbi_audit_org_reader",
    "rbi_audit_platform_reader",
    "rbi_current_user_org",
    "rbi_org_has_active_admin",
    "rbi_org_mfa_enabled_users",
    "rbi_platform_org_user_counts",
}


@pytest.fixture
def auditor(db: None) -> User:
    user = create_user("auditeur.mention@plateforme.rbi.test")
    grant_role(user, "AUDITOR")
    return user


def _register(admin: User, tag: str, *, is_demo: bool) -> Organization:
    scope = platform_scope(admin, purpose="tests")
    return services.register_organization(
        scope,
        name=f"Organisme {tag}",
        short_name=f"ORG-{tag}",
        type=Organization.Type.DOUANE,
        country_code="TG",
        timezone="Africa/Lome",
        retention_days=365,
        is_demo=is_demo,
    )


def drive_every_platform_event(admin: User, tag: str, *, is_demo: bool) -> set[str]:
    """Parcourt les neuf appels (succès et refus) pour un organisme ; renvoie les identifiants visés."""
    scope = platform_scope(admin, purpose="tests")
    admin_scope = platform_scope(admin, purpose="tests", permission="platform.institutional_admins")
    org = _register(admin, tag, is_demo=is_demo)
    services.update_organization(scope, org, name=f"Organisme {tag} renommé")
    with pytest.raises(InvalidTransition):
        services.suspend_organization(scope, org, reason="Transition interdite")  # EN_ATTENTE → SUSPENDUE
    valid_from = datetime.date(2026, 1, 1)
    services.authorize_organization(
        scope, org, reference=f"CONV-{tag}", scope_text="Périmètre fictif", valid_from=valid_from
    )
    services.add_authorization(
        scope, org, reference=f"AVN-{tag}", scope_text="Avenant", valid_from=valid_from
    )
    with pytest.raises(InvalidTransition):
        services.activate_organization(scope, org)  # aucun Administrateur institutionnel
    email = f"admin@{tag.lower()}.rbi.test"
    create_institutional_admin(admin_scope, org, email=email)
    response = signed_in(admin).post(
        f"/platform/organizations/{org.pk}/institutional-admins", {"email": email}
    )
    assert response.status_code == 400  # adresse déjà prise : refus journalisé par l'API
    late = _register(admin, f"{tag}-TARDIF", is_demo=is_demo)
    services.authorize_organization(
        scope,
        late,
        reference=f"FUT-{tag}",
        scope_text="Périmètre fictif",
        valid_from=datetime.date(2099, 1, 1),
    )
    with pytest.raises(InvalidTransition):
        services.activate_organization(scope, late)  # autorisation pas encore en vigueur
    return {str(org.pk), str(late.pk)}


def targeted(event: dict[str, Any], ids: set[str]) -> bool:
    return event["scope"] == "platform" and (
        event["organization_id"] in ids
        or (event["object_type"] == "organization" and event["object_id"] in ids)
    )


def audit_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Événements tels que préparés et écrits (journal technique ``rbi.audit``). En mode d'écriture « inline »
    des tests, un refus est écrit dans la transaction du service, annulée ensuite par l'exception ; en
    production (mode « autonomous »), il l'est par une connexion dédiée et conservé."""
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "rbi.audit"]


def targeted_rows(ids: set[str]) -> list[AuditLog]:
    with owner():
        rows = AuditLog.objects.filter(scope="platform").order_by("id")
        return [
            row
            for row in rows
            if str(row.organization_id) in ids or (row.object_type == "organization" and row.object_id in ids)
        ]


def export_rows(api: ApiClient) -> list[list[str]]:
    response = api.get(EXPORT)
    assert response.status_code == 200, response.content[:300]
    return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))


def by_id(rows: list[list[str]]) -> dict[str, list[str]]:
    position = 1 + CSV_COLUMNS.index("id")
    return {row[position]: row for row in rows[1:]}


# --- 1, 2. Statut enregistré à la création de l'événement ------------------------------------------------


@pytest.mark.parametrize("is_demo", [True, False], ids=["demonstration", "ordinaire"])
def test_every_platform_event_on_an_organisation_records_its_demo_status(
    platform_admin: User, is_demo: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="rbi.audit")
    ids = drive_every_platform_event(platform_admin, "DEMO" if is_demo else "ORD", is_demo=is_demo)
    events = [event for event in audit_events(caplog) if targeted(event, ids)]
    assert all(event["status"] == "recorded" for event in events)
    seen = {
        (e["action"], e["outcome"], e["details"].get("reason") if e["outcome"] != "success" else None)
        for e in events
    }
    assert seen == EXPECTED_EVENTS
    # Booléen exact (identité), pas une valeur « vraie » ou « fausse » au sens de Python.
    assert all(event["details"].get("demo") is is_demo for event in events), [
        (e["action"], e["outcome"], e["details"]) for e in events if e["details"].get("demo") is not is_demo
    ]
    rows = targeted_rows(ids)  # entrées validées : la valeur scellée est bien celle de l'événement
    assert rows and all(row.metadata.get("demo") is is_demo for row in rows)


def test_events_without_a_target_organisation_carry_no_demo_key(platform_admin: User) -> None:
    drive_every_platform_event(platform_admin, "DEMO", is_demo=True)
    with owner():
        untargeted = AuditLog.objects.filter(scope="platform", organization_id__isnull=True).exclude(
            object_type="organization"
        )
        assert untargeted.exists()
        assert not [row.action for row in untargeted if "demo" in row.metadata]


def test_seed_demo_events_are_all_marked(
    platform_admin: User, django_capture_on_commit_callbacks: Any
) -> None:
    from django.core.management import call_command

    with django_capture_on_commit_callbacks(execute=True):
        call_command("seed_demo", "--actor-email", platform_admin.email, stdout=io.StringIO())
    with owner():
        demo_ids = {str(pk) for pk in Organization.objects.filter(is_demo=True).values_list("pk", flat=True)}
    rows = targeted_rows(demo_ids)
    assert rows and all(row.metadata.get("demo") is True for row in rows)


# --- 3 à 6, 10. Mention de l'export ------------------------------------------------------------------


def test_platform_export_marks_each_row_from_its_recorded_status(platform_admin: User, auditor: User) -> None:
    demo_ids = drive_every_platform_event(platform_admin, "DEMO", is_demo=True)
    ordinary_ids = drive_every_platform_event(platform_admin, "ORD", is_demo=False)
    rows = export_rows(signed_in(auditor))
    header, body = rows[0], by_id(rows)
    assert header == ["mention", *CSV_COLUMNS]
    assert all(len(row) == len(header) for row in rows)  # CSV rectangulaire
    for entry in targeted_rows(demo_ids):
        assert body[str(entry.id)][0] == DEMO_MENTION, entry.action
    for entry in targeted_rows(ordinary_ids):
        assert body[str(entry.id)][0] == "", entry.action
    with owner():
        untargeted = AuditLog.objects.filter(scope="platform", organization_id__isnull=True).exclude(
            object_type="organization"
        )
        untargeted_ids = [str(pk) for pk in untargeted.values_list("id", flat=True)]
    assert untargeted_ids and all(body[i][0] == "" for i in untargeted_ids if i in body)


def _platform_entry(admin: User, org: Organization, details: dict[str, Any] | None) -> AuditLog:
    """Entrée écrite comme par une opération plateforme délivrée (politique d'insertion RLS respectée)."""
    with db_scope(current_user=admin.pk, current_org="", auth_email="", platform="platform.organizations"):
        record_event(
            "organization.update",
            outcome="success",
            actor_id=admin.pk,
            organization_id=org.pk,
            scope="platform",
            object_type="organization",
            object_id=org.pk,
            details=details,
        )
    with owner():
        return AuditLog.objects.filter(scope="platform").order_by("-id").first()  # type: ignore[return-value]


@pytest.mark.parametrize(
    "details",
    [None, {"demo": None}, {"demo": "true"}, {"demo": "false"}, {"demo": 1}, {"demo": 0}, {"other": True}],
    ids=["absente", "nulle", "texte-vrai", "texte-faux", "entier-1", "entier-0", "autre-cle"],
)
def test_missing_null_or_mistyped_status_is_undetermined_never_ordinary(
    platform_admin: User, auditor: User, details: dict[str, Any] | None
) -> None:
    org = _register(platform_admin, "INDET", is_demo=False)
    entry = _platform_entry(platform_admin, org, details)
    assert selectors.platform_demo_status(entry) == "undetermined"
    assert by_id(export_rows(signed_in(auditor)))[str(entry.id)][0] == UNDETERMINED_MENTION


def test_targeted_by_object_only_is_still_a_targeted_event() -> None:
    """Refus de désignation : organisme visé par l'objet, sans ``organization_id``."""
    entry = AuditLog(id=1, organization_id=None, object_type="organization", object_id="x", metadata={})
    assert selectors.platform_demo_status(entry) == "undetermined"
    entry.metadata = {"demo": True}
    assert selectors.platform_demo_status(entry) == "demo"


def test_an_event_without_organisation_never_receives_a_mention(auditor: User) -> None:
    with owner():
        record_event("auth.login", outcome="failure", actor_id=None, details={"demo": True})  # clé parasite
        entry = AuditLog.objects.filter(action="auth.login").order_by("-id").first()
    assert entry is not None and selectors.platform_demo_status(entry) is None
    assert by_id(export_rows(signed_in(auditor)))[str(entry.id)][0] == ""


def test_formulas_stay_neutralised_and_the_file_rectangular(platform_admin: User, auditor: User) -> None:
    org = _register(platform_admin, "FORMULE", is_demo=True)
    services.update_organization(platform_scope(platform_admin, purpose="tests"), org, name="=HYPERLINK(1)")
    _platform_entry(platform_admin, org, {"reason": "@SUM(A1)", "demo": True})
    rows = export_rows(signed_in(auditor))
    assert all(len(row) == len(rows[0]) for row in rows)
    assert not [cell for row in rows for cell in row if cell[:1] in FORMULA_STARTS]
    assert _cell("=1+1") == "'=1+1" and _cell(DEMO_MENTION) == DEMO_MENTION
    assert _cell(UNDETERMINED_MENTION) == UNDETERMINED_MENTION


# --- 7, 8. Périmètre et privilèges inchangés ---------------------------------------------------------


def test_the_export_never_reads_organisations_and_the_auditor_still_cannot(
    platform_admin: User, auditor: User
) -> None:
    drive_every_platform_event(platform_admin, "DEMO", is_demo=True)
    scope = platform_scope(auditor, purpose="export du journal plateforme", permission="platform.audit")
    with CaptureQueriesContext(connection) as queries:
        result = selectors.platform_export(scope, selectors.AuditQuery())
    assert result.statuses and "demo" in result.statuses.values()
    assert not [q["sql"] for q in queries.captured_queries if "organizations_organization" in q["sql"]]
    with db_scope(current_user=auditor.pk, current_org="", auth_email="", platform="platform.audit"):
        assert Organization.objects.count() == 0  # RLS : le périmètre d'audit ne voit aucun organisme
    assert signed_in(auditor).get("/platform/organizations").status_code == 403


def test_no_sql_function_privilege_or_policy_is_added() -> None:
    with owner(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.prosecdef AND has_function_privilege(%s, p.oid, 'EXECUTE')",
            [settings.RBI_DB_APP_ROLE],
        )
        definers = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT count(*) FROM pg_proc WHERE proname ILIKE '%%demo%%'")
        demo_functions = cursor.fetchone()[0]
        cursor.execute(
            "SELECT qual FROM pg_policies WHERE tablename = 'organizations_organization' AND cmd = 'SELECT'"
        )
        policies = [row[0] for row in cursor.fetchall()]
    assert definers == DEFINER_FUNCTIONS_FOR_APP
    assert demo_functions == 0
    assert policies and not [qual for qual in policies if "platform.audit" in qual]


# --- 9. Erreurs : refus explicite ---------------------------------------------------------------------


def test_a_status_that_cannot_be_established_refuses_the_export(
    platform_admin: User, auditor: User, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="rbi.audit")
    _register(platform_admin, "ERREUR", is_demo=True)

    def broken(row: AuditLog) -> Any:
        raise selectors.ExportMentionError(row.id)

    monkeypatch.setattr(selectors, "platform_demo_status", broken)
    response = signed_in(auditor).get(EXPORT)
    assert response.status_code == 500
    assert not response["Content-Type"].startswith("text/csv")
    # Refus journalisé (écrit dans la transaction de la requête en mode « inline », voir audit_events).
    exports = [e for e in audit_events(caplog) if e["action"] == "audit.export"]
    assert [(e["outcome"], e["details"]["reason"]) for e in exports] == [
        ("failure", "demo_status_unavailable")
    ]


def test_metadata_that_is_not_an_object_is_an_error_not_an_empty_cell() -> None:
    entry = AuditLog(id=1, organization_id=None, object_type=None, metadata=["demo"])
    with pytest.raises(selectors.ExportMentionError):
        selectors.platform_demo_status(entry)


def test_a_database_error_is_not_turned_into_a_file(auditor: User, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(*_: Any, **__: Any) -> Any:
        raise DatabaseError("lecture impossible (simulée)")

    monkeypatch.setattr(selectors, "_export", failing)
    with pytest.raises(DatabaseError):
        signed_in(auditor).get(EXPORT)
    with owner():
        assert not AuditLog.objects.filter(action="audit.export", outcome="success").exists()


def test_a_row_without_a_computed_status_is_an_error() -> None:
    row = AuditLog(
        id=7,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        scope="platform",
        actor_type="system",
        action="organization.update",
        outcome="success",
        metadata={},
        prev_hash="0" * 64,
        hash="1" * 64,
    )
    result = selectors.AuditResult(1, [row], {}, statuses={})
    with pytest.raises(KeyError):
        _csv_response(result, "plateforme")


# --- 11. Intégrité ----------------------------------------------------------------------------------


def test_changing_a_recorded_status_breaks_the_chain(platform_admin: User) -> None:
    org = _register(platform_admin, "SCELLE", is_demo=True)
    with owner():
        entry = AuditLog.objects.get(action="organization.register", organization_id=org.pk)
        assert entry.metadata["demo"] is True and verify_chain(PLATFORM_CHAIN).intact
    flip = "UPDATE audit_auditlog SET metadata = metadata || '{\"demo\": false}' WHERE id = %s"
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(flip, [entry.id])  # rôle applicatif : aucun droit de modification
    with (
        owner(),
        pytest.raises(DatabaseError, match="insertion seule"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(flip, [entry.id])  # propriétaire, déclencheurs actifs : refusé
    with owner(), connection.cursor() as cursor:  # administrateur de la base : déclencheurs désactivés
        cursor.execute("ALTER TABLE audit_auditlog DISABLE TRIGGER rbi_audit_immutable")
        cursor.execute(flip, [entry.id])
        cursor.execute("ALTER TABLE audit_auditlog ENABLE TRIGGER rbi_audit_immutable")
        report = verify_chain(PLATFORM_CHAIN)
    assert not report.intact
    assert any(str(entry.id) in error for error in report.errors), report.errors


# --- 12. Autorisations --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "expected"),
    [("auditor", 200), ("platform_admin", 200), ("admin_a", 403), ("sans_role", 403), ("anonyme", 403)],
)
def test_export_authorisation(
    auditor: User, platform_admin: User, admin_a: User, who: str, expected: int
) -> None:
    accounts = {"auditor": auditor, "platform_admin": platform_admin, "admin_a": admin_a}
    if who == "anonyme":
        api = ApiClient()
    elif who == "sans_role":
        api = signed_in(create_user("sans.role@plateforme.rbi.test"))
    else:
        api = signed_in(accounts[who])
    response = api.get(EXPORT)
    assert response.status_code in ((401, 403) if who == "anonyme" else (expected,)), response.content[:200]
    if expected == 200:
        assert response.content.decode("utf-8").startswith("mention,")
