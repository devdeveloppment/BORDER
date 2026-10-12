"""Isolation applicative entre organismes sur une donnée organisationnelle réelle (DataSource).

Ces tests couvrent les niveaux 2 et 3 de la défense en profondeur (§12.3). Le niveau base de données
(RLS PostgreSQL sur ces tables) est l'objet de P2.6.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.integrations import selectors
from apps.integrations.models import DataSource
from apps.organizations.exceptions import CrossTenantWriteError, TenantContextMissing
from apps.organizations.models import Organization
from apps.organizations.tenancy import TenantContext, tenant_context
from conftest import owner

pytestmark = pytest.mark.django_db


def ctx(org: Organization) -> TenantContext:
    return TenantContext(org.pk, "user")


@pytest.fixture
def sources(org_a: Organization, org_b: Organization) -> dict[str, DataSource]:
    with tenant_context(ctx(org_a)):
        a1 = DataSource.objects.create(name="Saisie poste 1", source_type="manuelle")
        a2 = DataSource.objects.create(name="Import mensuel", source_type="fichier")
    with tenant_context(ctx(org_b)):
        b1 = DataSource.objects.create(name="Flux API fictif", source_type="api", legal_basis_ref="CONV-B-1")
    return {"a1": a1, "a2": a2, "b1": b1}


def test_organization_assigned_from_context(sources: dict[str, DataSource], org_a: Organization) -> None:
    assert sources["a1"].organization_id == org_a.pk


def test_no_context_means_no_data(sources: dict[str, DataSource]) -> None:
    with pytest.raises(TenantContextMissing):
        DataSource.objects.all()
    with pytest.raises(TenantContextMissing):
        selectors.list_data_sources()
    with pytest.raises(TenantContextMissing):
        DataSource(name="Sans contexte", source_type="manuelle").save()


def test_each_organization_sees_only_its_own(
    sources: dict[str, DataSource], org_a: Organization, org_b: Organization
) -> None:
    with tenant_context(ctx(org_a)):
        assert {s.name for s in selectors.list_data_sources()} == {"Saisie poste 1", "Import mensuel"}
        # Un filtre client sur un autre organisme ne contourne rien.
        assert not DataSource.objects.filter(organization_id=org_b.pk).exists()
    with tenant_context(ctx(org_b)):
        assert [s.name for s in selectors.list_data_sources()] == ["Flux API fictif"]


def test_guessed_id_of_other_organization_indistinguishable_from_unknown(
    sources: dict[str, DataSource], org_a: Organization
) -> None:
    with tenant_context(ctx(org_a)):
        with pytest.raises(DataSource.DoesNotExist) as other:
            selectors.get_data_source(sources["b1"].pk)
        with pytest.raises(DataSource.DoesNotExist) as unknown:
            selectors.get_data_source(uuid.uuid4())
    assert str(other.value) == str(unknown.value)
    assert "Flux API fictif" not in str(other.value)


def test_cross_organization_writes_refused(
    sources: dict[str, DataSource], org_a: Organization, org_b: Organization
) -> None:
    with owner():  # objet obtenu hors RLS (simulation d'un contournement applicatif)
        foreign = DataSource._base_manager.get(
            pk=sources["b1"].pk
        )  # obtenu hors filtre (simulation d'un contournement)
    with tenant_context(ctx(org_a)):
        with pytest.raises(CrossTenantWriteError):
            DataSource(name="Injection", source_type="manuelle", organization_id=org_b.pk).save()
        foreign.name = "Modifié par A"
        with pytest.raises(CrossTenantWriteError):
            foreign.save()
        foreign.organization_id = org_a.pk  # tentative de « rapatriement »
        with pytest.raises(CrossTenantWriteError):
            foreign.save()
        with owner():
            intact = DataSource._base_manager.get(pk=sources["b1"].pk)
        with pytest.raises(CrossTenantWriteError):
            intact.delete()
        with pytest.raises(CrossTenantWriteError):
            DataSource.objects.bulk_create(
                [DataSource(name="Lot", source_type="manuelle", organization_id=org_b.pk)]
            )
        with pytest.raises(CrossTenantWriteError):
            DataSource.objects.update(organization_id=org_b.pk)
        # Mises à jour et suppressions de masse : limitées au périmètre du contexte.
        assert DataSource.objects.update(status="suspendue") == 2
        assert DataSource.objects.filter(pk=sources["b1"].pk).delete()[0] == 0
    with owner():
        stored = DataSource._base_manager.get(pk=sources["b1"].pk)
    assert (stored.name, stored.status, stored.organization_id) == ("Flux API fictif", "active", org_b.pk)


def test_names_unique_per_organization_only(sources: dict[str, DataSource], org_b: Organization) -> None:
    with tenant_context(ctx(org_b)):
        DataSource.objects.create(
            name="Saisie poste 1", source_type="manuelle"
        )  # même nom que chez A : permis
        with pytest.raises(IntegrityError), transaction.atomic():
            DataSource.objects.create(name="SAISIE POSTE 1", source_type="manuelle")


def test_api_source_requires_legal_basis(org_a: Organization) -> None:
    with tenant_context(ctx(org_a)), pytest.raises(IntegrityError), transaction.atomic():
        DataSource.objects.create(name="API sans convention", source_type="api")
