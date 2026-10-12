"""Enregistrement des événements : validation, contexte serveur, parcours réels (P2.7).

Mode ``inline`` des tests : l'événement est écrit dans la transaction du test, sous le rôle applicatif, et
contrôlé par le RLS comme en production. La conservation après annulation relève du mode autonome
(test_autonomous_writer.py).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import caches
from django.db import connection
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.audit.models import AppendOnlyError, AuditLog
from apps.audit.services import AuditWriteError, InvalidAuditEvent, record_event
from apps.authentication.tests.support import PASSWORD, Api, enroll, make_member, totp_code
from apps.core.db_scope import db_scope
from apps.core.request_context import REQUEST_ID_HEADER, request_context
from apps.organizations.models import Organization
from apps.organizations.tenancy import TenantContext, context_for_user, tenant_context
from apps.users.models import User
from apps.users.rbac import PermissionDeniedError, require_permission
from apps.users.services import assign_role, set_user_active
from conftest import grant_role, owner

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _isolated_throttling() -> Iterator[None]:
    caches["default"].clear()
    yield
    caches["default"].clear()


def events(**filters: Any) -> list[AuditLog]:
    with owner():
        return list(AuditLog.objects.filter(**filters).order_by("id"))


def last_event(**filters: Any) -> AuditLog:
    rows = events(**filters)
    assert rows, filters
    return rows[-1]


# --- Validation (avant toute écriture) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"action": "auth.unknown"}, "action inconnue"),
        ({"details": {"password": "Fictif-2026"}}, "clé refusée"),
        ({"details": {"totp_secret": "x"}}, "clé refusée"),
        ({"details": {"session_key": "x"}}, "clé refusée"),
        ({"details": {"Raison": "x"}}, "clé refusée"),
        ({"details": {"reason": "x" * 501}}, "trop longue"),
        ({"details": {"nested": {"a": 1}}}, "type non autorisé"),
        ({"details": {"items": list(range(51))}}, "trop d'éléments"),
        ({"old_value": {"backup_code": "1234"}}, "clé refusée"),
        ({"new_value": {"csrf": "t"}}, "clé refusée"),
        ({"object_type": "secret_store", "object_id": "1"}, "objet invalide"),
        ({"object_type": "user", "object_id": "a b"}, "objet invalide"),
        ({"system": True, "actor_id": uuid.uuid4()}, "action système"),
        ({"scope": "organization"}, "exige l'organisme"),
        ({"organization_id": "pas-un-uuid"}, "UUID attendu"),
    ],
)
def test_invalid_events_are_refused_before_writing(kwargs: dict[str, Any], message: str) -> None:
    values: dict[str, Any] = {"action": "audit.verify", "outcome": "success", "actor_id": None}
    values.update(kwargs)
    before = len(events())
    with pytest.raises(InvalidAuditEvent, match=message):
        record_event(values.pop("action"), **values)
    assert len(events()) == before


# --- Contexte serveur ----------------------------------------------------------------------------------


def test_event_carries_server_context(admin_a: User, org_a: Organization, user_a: User) -> None:
    request_id = uuid.uuid4()
    with (
        request_context(request_id=request_id, ip_address="192.0.2.10"),
        tenant_context(TenantContext(org_a.pk, "user", admin_a.pk)),
    ):
        set_user_active(admin_a, context_for_user(admin_a), user_a.pk, active=False)
    event = last_event(action="user.deactivate")
    assert (event.scope, event.organization_id, event.actor_type, event.actor_id) == (
        "organization",
        org_a.pk,
        "user",
        admin_a.pk,
    )
    assert (event.object_type, event.object_id) == ("user", str(user_a.pk))
    assert (event.old_value, event.new_value) == ({"is_active": True}, {"is_active": False})
    assert event.request_id == request_id and event.ip_address == "192.0.2.10"


def test_ip_address_is_not_recorded_when_disabled(settings: Any, user_a: User) -> None:
    settings.RBI_AUDIT_RECORD_IP = False
    with request_context(ip_address="192.0.2.10"):
        record_event(
            "auth.reauthenticate",
            outcome="failure",
            actor_id=user_a.pk,
            organization_id=user_a.organization_id,
        )
    assert last_event(action="auth.reauthenticate").ip_address is None


def test_invalid_peer_address_is_discarded(user_a: User) -> None:
    with request_context(ip_address="unknown"):
        record_event(
            "auth.reauthenticate",
            outcome="failure",
            actor_id=user_a.pk,
            organization_id=user_a.organization_id,
        )
    assert last_event(action="auth.reauthenticate").ip_address is None


def test_event_for_another_organization_is_refused_by_postgresql(
    admin_a: User, org_a: Organization, org_b: Organization
) -> None:
    """Un appelant qui attribuerait un événement à un autre organisme que celui du contexte serveur échoue :
    rien n'est écrit dans le journal de B."""
    with tenant_context(TenantContext(org_a.pk, "user", admin_a.pk)), pytest.raises(AuditWriteError):
        record_event("user.create", outcome="success", actor_id=admin_a.pk, organization_id=org_b.pk)
    assert events(organization_id=org_b.pk) == []


def test_event_attributed_to_another_actor_is_refused(
    admin_a: User, user_a: User, org_a: Organization
) -> None:
    with tenant_context(TenantContext(org_a.pk, "user", admin_a.pk)), pytest.raises(AuditWriteError):
        record_event("user.create", outcome="success", actor_id=user_a.pk, organization_id=org_a.pk)


def test_rbac_denial_is_attributed_to_the_actor_organization(
    user_a: User, org_a: Organization, org_b: Organization
) -> None:
    """Contexte d'un autre organisme présenté à require_permission : refus enregistré chez l'acteur (A),
    jamais dans le journal de B."""
    grant_role(user_a, "AGENT")
    with pytest.raises(PermissionDeniedError):
        require_permission(user_a, "users.manage", TenantContext(org_b.pk, "user", user_a.pk))
    event = last_event(action="rbac.check")
    assert (event.organization_id, event.outcome, event.actor_id) == (org_a.pk, "denied", user_a.pk)
    assert event.metadata == {"permission": "users.manage", "context_mismatch": True}
    assert events(organization_id=org_b.pk) == []


def test_role_change_records_old_and_new_values(admin_a: User, user_a: User, org_a: Organization) -> None:
    context = context_for_user(admin_a)
    assign_role(admin_a, context, user_a.pk, "SUPERVISOR")
    event = last_event(action="user.role.assign")
    assert event.new_value == {"role": "SUPERVISOR"} and event.object_id == str(user_a.pk)


def test_system_action_is_explicit(platform_admin: User) -> None:
    record_event(
        "audit.verify", outcome="success", actor_id=None, system=True, details={"channel": "maintenance"}
    )
    event = last_event(action="audit.verify")
    assert (event.actor_type, event.actor_id, event.scope, event.organization_id) == (
        "system",
        None,
        "platform",
        None,
    )


def test_platform_operation_is_identified(platform_admin: User) -> None:
    from apps.organizations.platform import platform_scope

    scope = platform_scope(platform_admin, purpose="tests")
    event = last_event(action="platform.scope")
    assert (event.scope, event.actor_id, event.metadata["permission"]) == (
        "platform",
        platform_admin.pk,
        "platform.organizations",
    )
    assert scope.actor_id == platform_admin.pk


def test_record_event_restores_database_scope(admin_a: User, org_a: Organization) -> None:
    with db_scope(current_org=org_a.pk, current_user=admin_a.pk, auth_email="", platform=""):
        record_event("user.create", outcome="denied", actor_id=admin_a.pk, organization_id=org_a.pk)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, current_setting('app.current_org', true)")
            role, org = cursor.fetchone()
    assert org == str(org_a.pk)  # périmètre restauré après l'écriture
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone() == (role,)


# --- Le modèle Django ne permet ni modification ni suppression -----------------------------------------


def test_orm_cannot_modify_or_delete(user_a: User) -> None:
    record_event(
        "auth.reauthenticate", outcome="failure", actor_id=user_a.pk, organization_id=user_a.organization_id
    )
    with owner():
        entry = AuditLog.objects.filter(actor_id=user_a.pk).latest("id")
        for attempt in (
            entry.save,
            entry.delete,
            lambda: AuditLog.objects.filter(pk=entry.pk).update(outcome="success"),
            lambda: AuditLog.objects.filter(pk=entry.pk).delete(),
            lambda: AuditLog.objects.create(action="audit.read"),
            lambda: AuditLog.objects.bulk_create([AuditLog(action="audit.read")]),
        ):
            with pytest.raises(AppendOnlyError):
                attempt()


# --- Parcours HTTP réels -------------------------------------------------------------------------------


def test_failed_login_is_recorded_without_identifier_or_password(api: Api, user_a: User) -> None:
    response = api.post("/auth/login", {"email": user_a.email, "password": "Mauvais-Mdp-2026!"})
    assert response.status_code == 401
    event = last_event(action="auth.login", outcome="failure")
    assert (event.actor_type, event.scope, event.organization_id) == ("anonymous", "platform", None)
    assert str(event.request_id) == response[REQUEST_ID_HEADER]
    text = json.dumps([event.metadata, event.old_value, event.new_value])
    assert user_a.email not in text and "Mauvais-Mdp-2026!" not in text


def test_client_request_id_is_ignored(api: Api, user_a: User) -> None:
    forged = str(uuid.uuid4())
    response = api.post(
        "/auth/login", {"email": user_a.email, "password": "x"}, headers={REQUEST_ID_HEADER: forged}
    )
    assert response[REQUEST_ID_HEADER] != forged
    assert str(last_event(action="auth.login").request_id) == response[REQUEST_ID_HEADER]


def test_successful_login_and_logout_are_recorded(api: Api, org_a: Organization) -> None:
    agent = make_member(org_a, "AGENT", "agent.audit@demo-a.rbi.test")
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).status_code == 200
    assert api.post("/auth/logout").status_code == 204
    actions = [(e.action, e.outcome) for e in events(actor_id=agent.pk)]
    assert actions == [("auth.session.open", "success"), ("auth.session.close", "success")]
    assert {e.organization_id for e in events(actor_id=agent.pk)} == {org_a.pk}


def test_login_refused_for_suspended_organization_is_recorded(api: Api, org_a: Organization) -> None:
    agent = make_member(org_a, "AGENT", "agent.suspendu@demo-a.rbi.test")
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    assert api.post("/auth/login", {"email": agent.email, "password": PASSWORD}).status_code == 403
    event = last_event(action="auth.login", outcome="denied")
    assert (event.organization_id, event.actor_id, event.metadata["reason"]) == (
        org_a.pk,
        agent.pk,
        "organization_not_active",
    )


def test_mfa_flow_records_no_secret(api: Api, org_a: Organization) -> None:
    """Enrôlement, code faux, code juste, code de secours : ni secret TOTP, ni code, ni mot de passe, ni
    cookie dans le journal."""
    supervisor = make_member(org_a, "SUPERVISOR", "superviseur.audit@demo-a.rbi.test")
    backup_codes = enroll(api, supervisor)
    api.post("/auth/logout")
    assert api.post("/auth/login", {"email": supervisor.email, "password": PASSWORD}).status_code == 200
    assert api.post("/auth/mfa/verify", {"code": "000000"}).status_code == 400
    assert api.post("/auth/mfa/verify", {"code": backup_codes[0]}).status_code == 200
    with owner():
        device = TOTPDevice.objects.get(user=supervisor, confirmed=True)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT string_agg(concat_ws(' ', action, object_id, metadata::text, old_value::text, "
                "new_value::text), E'\\n') FROM audit_auditlog WHERE actor_id = %s",
                [supervisor.pk],
            )
            journal = cursor.fetchone()[0]
    for secret in (PASSWORD, device.key, totp_code(device), *backup_codes, api.session_key or "-", "000000"):
        assert secret not in journal
    outcomes = [
        (e.action, e.outcome) for e in events(actor_id=supervisor.pk) if e.action == "auth.mfa.verify"
    ]
    assert outcomes == [
        ("auth.mfa.verify", "success"),
        ("auth.mfa.verify", "failure"),
        ("auth.mfa.verify", "success"),
    ]
    assert last_event(action="auth.mfa.verify", actor_id=supervisor.pk).metadata == {"method": "backup_code"}


def test_tenant_refusal_is_recorded(user_a: User, org_a: Organization) -> None:
    """Organisme suspendu pendant une session : le middleware refuse le contexte (403) et l'enregistre. (Par
    HTTP, le backend d'authentification ferme déjà la session : ce chemin couvre la fenêtre entre les
    deux.)"""
    from django.http import HttpResponse
    from django.test import RequestFactory

    from apps.organizations.middleware import TenantContextMiddleware

    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    request = RequestFactory().get("/api/v1/me")
    request.user = user_a
    response = TenantContextMiddleware(lambda _: HttpResponse())(request)
    assert response.status_code == 403
    event = last_event(action="tenant.access")
    assert (event.outcome, event.actor_id, event.organization_id) == ("denied", user_a.pk, org_a.pk)


@pytest.fixture
def api() -> Api:
    return Api()
