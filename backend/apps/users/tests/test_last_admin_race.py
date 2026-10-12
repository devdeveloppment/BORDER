"""Dernier Administrateur institutionnel : désactivations croisées concurrentes.

Deux administrateurs A et B d'un même organisme se désactivent mutuellement au même moment. La règle « le
dernier Administrateur institutionnel actif ne peut être ni retiré ni désactivé » doit tenir : une seule des
deux opérations aboutit. Test transactionnel (deux connexions réelles), ordonnancement forcé : la première
transaction garde ses verrous jusqu'à ce que la seconde soit bloquée sur eux.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.db import connection, transaction

from apps.audit import writer
from apps.organizations.models import Organization
from apps.organizations.tenancy import context_for_user
from apps.users.models import User
from apps.users.services import LastAdministratorError, revoke_role, set_user_active
from conftest import create_user, grant_role

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def autonomous(settings: Any) -> Any:
    settings.RBI_AUDIT_WRITE_MODE = "autonomous"  # transactions réellement validées : écrivain de production
    yield
    writer.close_connection()


def _deactivate(actor: User, target: User) -> None:
    set_user_active(actor, context_for_user(actor), target.pk, active=False)


def _revoke(actor: User, target: User) -> None:
    revoke_role(actor, context_for_user(actor), target.pk, "ORG_ADMIN")


def _active_admins(*users: User) -> int:
    return sum(
        1
        for u in User.objects.filter(pk__in=[u.pk for u in users], is_active=True)
        if u.role_assignments.filter(role__code="ORG_ADMIN").exists()
    )


@pytest.mark.parametrize("second_operation", [_deactivate, _revoke], ids=["deactivate", "revoke"])
def test_crossed_operations_on_the_last_two_admins_leave_one_active(
    org_a: Organization, second_operation: Any
) -> None:
    first = create_user("admin1@demo-a.rbi.test", org_a)
    second = create_user("admin2@demo-a.rbi.test", org_a)
    grant_role(first, "ORG_ADMIN")
    grant_role(second, "ORG_ADMIN")
    holding, release = threading.Event(), threading.Event()
    outcome: dict[str, str] = {}

    def run(name: str, operation: Any, actor: User, target: User, hold: bool) -> None:
        try:
            with connection.cursor() as cursor:  # connexion du thread : rôle applicatif, soumis au RLS
                cursor.execute("SET ROLE %s" % connection.ops.quote_name(django_settings.RBI_DB_APP_ROLE))  # noqa: UP031
            with transaction.atomic():
                operation(actor, target)
                if hold:
                    holding.set()
                    release.wait(10)
            outcome[name] = "ok"
        except LastAdministratorError:
            outcome[name] = "refused"
        except Exception as exc:  # pragma: no cover - diagnostic
            outcome[name] = f"error: {exc!r}"
        finally:
            connection.close()

    one = threading.Thread(target=run, args=("first", _deactivate, first, second, True))
    one.start()
    assert holding.wait(10)
    two = threading.Thread(target=run, args=("second", second_operation, second, first, False))
    two.start()
    time.sleep(1.0)  # la seconde transaction atteint le verrou tenu par la première
    release.set()
    one.join(20)
    two.join(20)

    assert outcome == {"first": "ok", "second": "refused"}, outcome
    assert _active_admins(first, second) == 1
