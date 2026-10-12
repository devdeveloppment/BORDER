"""Sources de données déclarées par un organisme (§8.3, §14.3).

Une source de données est distincte de l'organisme (qui la possède) et des utilisateurs (qui l'administrent) :
c'est le canal par lequel des données entrent dans l'espace de l'organisme (saisie, fichier, API, connecteur).
Les identifiants machine (clé API / OAuth2) et le connecteur (SystemIntegration) seront ajoutés
avec l'ingestion ;
aucun secret n'est stocké ici. Aucun système réel n'est raccordé.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.organizations.models import TenantScopedModel


class DataSourceType(models.TextChoices):
    MANUELLE = "manuelle", "Saisie manuelle"
    FICHIER = "fichier", "Import de fichier"
    API = "api", "API"
    CONNECTEUR = "connecteur", "Connecteur"


class DataSourceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDUE = "suspendue", "Suspendue"


class DataSource(TenantScopedModel):
    SourceType = DataSourceType

    Status = DataSourceStatus

    name = models.CharField("nom", max_length=150)
    source_type = models.CharField("type", max_length=20, choices=SourceType.choices)
    legal_basis_ref = models.CharField("référence d'autorisation", max_length=100, blank=True)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    last_received_at = models.DateTimeField("dernière réception", null=True, blank=True)

    class Meta:
        verbose_name = "source de données"
        verbose_name_plural = "sources de données"
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint("organization", Lower("name"), name="data_source_name_unique_per_org"),
            models.CheckConstraint(
                condition=Q(source_type__in=DataSourceType.values), name="data_source_type_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=DataSourceStatus.values), name="data_source_status_valid"
            ),
            models.CheckConstraint(
                condition=~Q(source_type__in=["api", "connecteur"]) | ~Q(legal_basis_ref=""),
                name="data_source_legal_basis_required",
            ),
            models.CheckConstraint(condition=~Q(name=""), name="data_source_name_not_blank"),
        )
        indexes = (models.Index(fields=("organization", "status"), name="data_source_org_status_idx"),)

    def __str__(self) -> str:
        return self.name
