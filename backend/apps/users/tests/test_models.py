from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

# Contraintes de schéma et catalogue : vérifiées avec le rôle propriétaire (hors RLS).
pytestmark = [pytest.mark.django_db, pytest.mark.db_owner]


def test_user_identified_by_email_with_uuid_pk() -> None:
    user = get_user_model().objects.create_user(
        email="Agent.Demo@Demo-A.RBI.test", password="Fictif-2026-mdp!"
    )
    assert user.email == "agent.demo@demo-a.rbi.test"
    assert user.pk.version == 4
    assert user.check_password("Fictif-2026-mdp!")
    assert user.password != "Fictif-2026-mdp!"
    # Aucun court-circuit des autorisations : pas d'is_superuser, de groupes ni de permissions Django (P2.4).
    assert not hasattr(user, "is_superuser")
    assert not hasattr(user, "user_permissions")


def test_email_is_required() -> None:
    with pytest.raises(ValueError, match="e-mail"):
        get_user_model().objects.create_user(email="", password="x")
