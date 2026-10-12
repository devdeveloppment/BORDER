"""Contexte d'organisme : aucune valeur implicite, déduit du serveur, restauré, propre à chaque thread."""

from __future__ import annotations

import threading
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.test import RequestFactory

from apps.organizations import selectors
from apps.organizations.exceptions import TenantAccessDenied, TenantContextMissing
from apps.organizations.middleware import TenantContextMiddleware
from apps.organizations.models import Organization
from apps.organizations.tasking import tenant_task
from apps.organizations.tenancy import (
    TenantContext,
    context_for_task,
    context_for_user,
    current_tenant_or_none,
    get_current_tenant,
    tenant_context,
)
from apps.users.models import User
from conftest import owner

pytestmark = pytest.mark.django_db


def test_no_implicit_context() -> None:
    assert current_tenant_or_none() is None
    with pytest.raises(TenantContextMissing):
        get_current_tenant()


def test_context_is_restored_even_after_errors(org_a: Organization, org_b: Organization) -> None:
    ctx_a = TenantContext(org_a.pk, "user")
    ctx_b = TenantContext(org_b.pk, "user")
    with tenant_context(ctx_a):
        with pytest.raises(RuntimeError), tenant_context(ctx_b):
            assert get_current_tenant() == ctx_b
            raise RuntimeError
        assert get_current_tenant() == ctx_a
    assert current_tenant_or_none() is None


def test_context_not_shared_with_other_threads(org_a: Organization) -> None:
    seen: list[TenantContext | None] = []
    with tenant_context(TenantContext(org_a.pk, "user")):
        thread = threading.Thread(target=lambda: seen.append(current_tenant_or_none()))
        thread.start()
        thread.join()
    assert seen == [None]


def test_tenant_context_rejects_raw_identifiers(org_a: Organization) -> None:
    with pytest.raises(TypeError), tenant_context(org_a.pk):  # type: ignore[arg-type]
        pass


def test_context_for_organization_user(user_a: User, org_a: Organization) -> None:
    assert context_for_user(user_a) == TenantContext(org_a.pk, "user", user_a.pk)


@pytest.mark.parametrize("status", ["EN_ATTENTE", "AUTORISEE", "SUSPENDUE", "ARCHIVEE"])
def test_no_context_unless_organization_active(user_a: User, org_a: Organization, status: str) -> None:
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=status)
    with owner():
        reloaded = User.objects.get(pk=user_a.pk)
    with pytest.raises(TenantAccessDenied):
        context_for_user(reloaded)


def test_no_context_for_platform_inactive_or_anonymous(platform_admin: User, user_a: User) -> None:
    with pytest.raises(TenantAccessDenied, match="plateforme"):
        context_for_user(platform_admin)  # le Super Admin n'accède pas aux données opérationnelles
    with pytest.raises(TenantAccessDenied):
        context_for_user(AnonymousUser())
    user_a.is_active = False
    with pytest.raises(TenantAccessDenied):
        context_for_user(user_a)


def test_own_organization_selector(user_a: User, org_a: Organization) -> None:
    assert selectors.get_own_organization(context_for_user(user_a)) == org_a


# --- Middleware -------------------------------------------------------------------------------


def _capture_view(captured: list[TenantContext | None]):  # type: ignore[no-untyped-def]
    def view(request: HttpRequest) -> HttpResponse:
        captured.append(current_tenant_or_none())
        return JsonResponse({})

    return view


def test_middleware_uses_authenticated_user_only(
    user_a: User, org_a: Organization, org_b: Organization
) -> None:
    captured: list[TenantContext | None] = []
    middleware = TenantContextMiddleware(_capture_view(captured))
    request = RequestFactory().get(
        f"/api/v1/x?organization_id={org_b.pk}",
        headers={"X-Organization-Id": str(org_b.pk)},
    )
    request.user = user_a
    response = middleware(request)
    assert response.status_code == 200
    assert captured == [TenantContext(org_a.pk, "user", user_a.pk)]  # paramètre et en-tête client ignorés
    assert current_tenant_or_none() is None  # contexte retiré après la requête


def test_middleware_without_user_or_for_platform_sets_no_context(platform_admin: User) -> None:
    captured: list[TenantContext | None] = []
    middleware = TenantContextMiddleware(_capture_view(captured))
    anonymous = RequestFactory().get("/", headers={"X-Organization-Id": str(uuid.uuid4())})
    middleware(anonymous)  # pas de request.user tant que l'authentification (P2.5) n'existe pas
    platform = RequestFactory().get("/")
    platform.user = platform_admin
    middleware(platform)
    assert captured == [None, None]


def test_middleware_blocks_suspended_organization(user_a: User, org_a: Organization) -> None:
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    captured: list[TenantContext | None] = []
    request = RequestFactory().get("/")
    with owner():
        request.user = User.objects.get(pk=user_a.pk)
    response = TenantContextMiddleware(_capture_view(captured))(request)
    assert response.status_code == 403
    assert captured == []
    assert b"SUSPENDUE" not in response.content


# --- Tâches asynchrones -----------------------------------------------------------------------


@tenant_task
def _probe_task(*, organization_id: str) -> uuid.UUID:
    return get_current_tenant().organization_id


def test_task_runs_in_explicit_context(org_a: Organization) -> None:
    assert _probe_task(organization_id=str(org_a.pk)) == org_a.pk
    assert current_tenant_or_none() is None


def test_task_without_or_with_invalid_context_refused(org_a: Organization) -> None:
    with pytest.raises(TenantContextMissing):
        _probe_task()  # type: ignore[call-arg]
    with pytest.raises(TenantAccessDenied):
        _probe_task(organization_id="pas-un-uuid")
    with pytest.raises(TenantAccessDenied):
        _probe_task(organization_id=str(uuid.uuid4()))
    with owner():
        Organization.objects.filter(pk=org_a.pk).update(status=Organization.Status.SUSPENDUE)
    with pytest.raises(TenantAccessDenied):
        _probe_task(organization_id=str(org_a.pk))  # SUSPENDUE : aucune ingestion
    with pytest.raises(TenantContextMissing):
        context_for_task(None)
