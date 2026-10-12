"""Contraintes du modèle Organisation, de l'autorisation formelle et de la demande d'accès (base réelle)."""

from __future__ import annotations

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.db.models import ProtectedError

from apps.organizations.models import AccessRequest, Organization
from apps.users.models import User
from conftest import OrganizationFactory, add_authorization

# Contraintes de schéma et catalogue : vérifiées avec le rôle propriétaire (hors RLS).
pytestmark = [pytest.mark.django_db, pytest.mark.db_owner]


def test_defaults_and_uuid(make_organization: OrganizationFactory) -> None:
    org = Organization.objects.create(
        name="Organisme Neuf",
        short_name="NEUF",
        type="autre",
        country_code="TG",
        timezone="UTC",
        retention_days=30,
    )
    assert org.status == Organization.Status.EN_ATTENTE  # jamais actif par défaut
    assert org.deployment_mode == Organization.DeploymentMode.MUTUALISE
    assert org.is_demo is False
    assert org.pk.version == 4
    assert org.created_at is not None and org.updated_at is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "INCONNU"),
        ("type", "armee"),
        ("deployment_mode", "cloud"),
        ("country_code", "tg"),
        ("country_code", "TGO"),
        ("retention_days", 0),
        ("name", ""),
        ("short_name", ""),
    ],
)
def test_database_rejects_invalid_values(
    make_organization: OrganizationFactory, field: str, value: object
) -> None:
    org = make_organization()
    with pytest.raises((IntegrityError, DataError)), transaction.atomic():
        Organization.objects.filter(pk=org.pk).update(**{field: value})


def test_names_unique_case_insensitive(make_organization: OrganizationFactory) -> None:
    make_organization(name="Organisme Démo X", short_name="DX")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_organization(name="ORGANISME DÉMO X", short_name="DX2")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_organization(name="Autre nom", short_name="dx")


def test_application_validation(make_organization: OrganizationFactory) -> None:
    org = make_organization()
    org.timezone = "Mars/Olympus"
    org.country_code = "tg"
    with pytest.raises(ValidationError) as excinfo:
        org.full_clean()
    assert {"timezone", "country_code"} <= excinfo.value.message_dict.keys()


def test_authorization_period_and_reference(org_a: Organization, platform_admin: User) -> None:
    add_authorization(org_a, platform_admin)
    with pytest.raises(IntegrityError), transaction.atomic():
        add_authorization(org_a, platform_admin)  # même référence pour le même organisme
    with pytest.raises(IntegrityError), transaction.atomic():
        add_authorization(
            org_a,
            platform_admin,
            reference="CONV-2",
            valid_from=datetime.date(2026, 6, 1),
            valid_until=datetime.date(2026, 5, 31),
        )


def test_access_request_requires_consent_and_consistent_processing() -> None:
    base = {
        "organization_name": "Organisme Demandeur Fictif",
        "requester_name": "Personne Fictive",
        "requester_role": "Chef de service",
        "email": "contact@demandeur.rbi.test",
        "request_type": "acces",
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        AccessRequest.objects.create(**base, consent=False)
    with pytest.raises(IntegrityError), transaction.atomic():
        AccessRequest.objects.create(**base, consent=True, status=AccessRequest.Status.TRAITEE)  # sans date


def test_separation_organization_user_data_source(org_a: Organization, user_a: User) -> None:
    """Organisme, utilisateur et source de données sont trois entités distinctes reliées par clé étrangère."""
    from apps.integrations.models import DataSource

    user_fields = {f.name for f in User._meta.get_fields()}
    source_fields = {f.name for f in DataSource._meta.get_fields()}
    assert "organization" in user_fields and "organization" in source_fields
    assert not {"email", "password"} & source_fields  # une source n'est pas un compte
    assert not {"source_type", "legal_basis_ref"} & user_fields
    assert user_a.organization == org_a
    assert not hasattr(org_a, "datasource_set")  # aucune relation inverse non filtrée


def test_organization_with_users_cannot_be_deleted(org_a: Organization, user_a: User) -> None:
    with pytest.raises(ProtectedError):
        org_a.delete()


def test_platform_account_has_no_organization(platform_admin: User, user_a: User) -> None:
    assert platform_admin.is_platform_account
    assert not user_a.is_platform_account
