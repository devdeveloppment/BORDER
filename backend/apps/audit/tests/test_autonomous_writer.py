"""Écriture autonome (mode de production) : conservation des refus, succès après COMMIT, concurrence (P2.7).

Tests transactionnels : les données de test sont réellement validées, donc visibles de la connexion d'écriture
dédiée. Les entrées d'audit écrites ici restent dans la base de test (le journal n'est jamais vidé : table
hors du nettoyage de pytest-django) ; chaque test ne regarde que ses propres organismes et comptes.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import transaction

from apps.audit import writer
from apps.audit.integrity import verify_chain
from apps.audit.models import AuditLog
from apps.audit.services import AuditWriteError, prepare_event, record_event
from apps.organizations import services as organizations
from apps.organizations.exceptions import InvalidTransition
from apps.organizations.models import Organization
from apps.organizations.platform import platform_scope
from apps.organizations.tasking import tenant_task
from apps.organizations.tenancy import context_for_user
from apps.users.models import User
from apps.users.services import SelfManagementError, create_organization_user, set_user_active

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def autonomous(settings: Any) -> Iterator[None]:
    settings.RBI_AUDIT_WRITE_MODE = "autonomous"
    yield
    writer.close_connection()


def entries(**filters: Any) -> list[AuditLog]:
    return list(AuditLog.objects.filter(**filters).order_by("id"))  # rôle propriétaire : hors RLS


def test_writer_runs_as_application_role_on_its_own_connection() -> None:
    conn = writer._connection()
    assert conn.execute("SELECT current_user").fetchone() == (os.environ["RBI_DB_APP_USER"],)
    assert conn.info.transaction_status.name == "IDLE"  # aucune transaction laissée ouverte


def test_writer_leaves_no_context_on_its_connection(admin_a: User, org_a: Organization) -> None:
    record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    row = (
        writer._connection()
        .execute(
            "SELECT coalesce(current_setting('app.current_org', true), ''), "
            "coalesce(current_setting('app.current_user', true), '')"
        )
        .fetchone()
    )
    assert row == ("", "")


def test_denial_survives_rollback_of_the_business_transaction(admin_a: User, org_a: Organization) -> None:
    """Désactivation de son propre compte : refus enregistré PUIS transaction métier annulée."""
    with pytest.raises(SelfManagementError):
        set_user_active(admin_a, context_for_user(admin_a), admin_a.pk, active=False)
    [event] = entries(actor_id=admin_a.pk, action="user.set_active")
    assert (event.outcome, event.organization_id, event.metadata) == (
        "denied",
        org_a.pk,
        {"reason": "self_management"},
    )
    assert User.objects.get(pk=admin_a.pk).is_active  # l'opération, elle, n'a rien changé


def test_success_is_recorded_only_after_commit(admin_a: User, org_a: Organization) -> None:
    with transaction.atomic():
        record_event("auth.password.change", outcome="success", actor_id=admin_a.pk, organization_id=org_a.pk)
        assert entries(actor_id=admin_a.pk) == []  # pas avant la validation
    assert [e.action for e in entries(actor_id=admin_a.pk)] == ["auth.password.change"]


def test_success_of_a_rolled_back_operation_is_not_recorded(admin_a: User, org_a: Organization) -> None:
    with pytest.raises(RuntimeError), transaction.atomic():
        record_event("auth.password.change", outcome="success", actor_id=admin_a.pk, organization_id=org_a.pk)
        raise RuntimeError("échec métier après l'événement")
    assert entries(actor_id=admin_a.pk) == []


def test_real_service_success_is_recorded(admin_a: User, org_a: Organization) -> None:
    user = create_organization_user(admin_a, context_for_user(admin_a), email="nouveau@demo-a.rbi.test")
    [event] = entries(action="user.create", object_id=str(user.pk))
    assert (event.actor_id, event.organization_id, event.outcome) == (admin_a.pk, org_a.pk, "success")


def test_denial_while_business_transaction_holds_locks_does_not_deadlock(
    platform_admin: User, make_organization: Any
) -> None:
    """La transaction métier verrouille la ligne de l'organisme (SELECT … FOR UPDATE) puis enregistre un
    refus : la connexion d'écriture ne dépend d'aucun de ces verrous (pas de clé étrangère, tête de chaîne
    propre)."""
    org = make_organization(status=Organization.Status.AUTORISEE)  # aucune autorisation formelle en vigueur
    writer._connection().execute("SET lock_timeout = '5s'")  # un interblocage échouerait au lieu de bloquer
    with pytest.raises(InvalidTransition):
        organizations.activate_organization(platform_scope(platform_admin, purpose="tests"), org)
    [event] = entries(action="organization.activate", organization_id=org.pk)
    assert (event.outcome, event.scope, event.metadata) == (
        "denied",
        "platform",
        {"reason": "no_valid_authorization"},
    )


def test_concurrent_writers_keep_every_chain_intact(org_a: Organization, org_b: Organization) -> None:
    """8 threads de 15 événements répartis sur trois chaînes : aucun lien rompu, identifiants dans l'ordre du
    chaînage, têtes de chaîne exactes."""
    before = {key: verify_chain(key).checked for key in (str(org_a.pk), str(org_b.pk), "platform")}
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            for i in range(15):
                org = (org_a, org_b, None)[(n + i) % 3]
                event = prepare_event(
                    "audit.verify",
                    outcome="success",
                    actor_id=None,
                    system=True,
                    organization_id=org.pk if org else None,
                    details={"thread": n, "index": i},
                )
                writer.write(dataclasses.replace(event, context_org=str(org.pk) if org else ""))
        except BaseException as exc:  # remonté au thread principal
            errors.append(exc)
        finally:
            writer.close_connection()

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    reports = {key: verify_chain(key) for key in before}
    assert all(report.intact for report in reports.values()), {k: r.errors for k, r in reports.items()}
    assert sum(reports[key].checked - before[key] for key in before) == 120


def test_write_failure_aborts_the_operation(admin_a: User, org_b: Organization, caplog: Any) -> None:
    """Événement refusé par PostgreSQL (organisme non autorisé) : l'appelant échoue, rien n'est écrit, et la
    perte est signalée en CRITIQUE sur le journal technique."""
    caplog.set_level(logging.INFO, logger="rbi.audit")
    with pytest.raises(AuditWriteError):
        record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_b.pk)
    assert entries(organization_id=org_b.pk) == []
    assert any(r.levelno == logging.CRITICAL and "write_failed" in r.getMessage() for r in caplog.records)


def test_write_failure_after_commit_is_reported_not_hidden(
    admin_a: User, org_b: Organization, caplog: Any
) -> None:
    """Après le COMMIT, l'opération ne peut plus être annulée : la perte est consignée en CRITIQUE (limite
    documentée), jamais silencieuse."""
    caplog.set_level(logging.INFO, logger="rbi.audit")
    with transaction.atomic():
        record_event("auth.password.change", outcome="success", actor_id=admin_a.pk, organization_id=org_b.pk)
    assert entries(organization_id=org_b.pk) == []
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.CRITICAL]
    assert any("write_failed" in m for m in messages)
    assert any("perdu après validation" in m for m in messages)


def test_task_events_are_attributed_to_the_task_organization(org_a: Organization) -> None:
    @tenant_task
    def task(*, organization_id: str) -> None:
        record_event("audit.verify", outcome="failure", actor_id=None, system=True, organization_id=org_a.pk)

    task(organization_id=str(org_a.pk))
    [event] = entries(organization_id=org_a.pk, action="audit.verify")
    assert (event.actor_type, event.scope) == ("system", "organization")


def test_new_connection_after_fork() -> None:
    first = writer._connection()
    writer._local.pid = -1  # processus enfant simulé : la connexion héritée n'est pas réutilisée
    second = writer._connection()
    assert second is not first
    first.close()


def test_request_id_is_preserved(admin_a: User, org_a: Organization) -> None:
    from apps.core.request_context import request_context

    request_id = uuid.uuid4()
    with request_context(request_id=request_id, ip_address="198.51.100.7"):
        record_event("auth.reauthenticate", outcome="failure", actor_id=admin_a.pk, organization_id=org_a.pk)
    [event] = entries(request_id=request_id)
    assert event.ip_address == "198.51.100.7"


def test_writer_connection_is_closed_at_the_end_of_each_request() -> None:
    from django.test import Client

    writer._connection()  # connexion d'écriture ouverte dans ce thread…
    Client().get("/api/v1/health/live")
    assert getattr(writer._local, "conn", None) is None  # …et fermée par la fin de la requête
