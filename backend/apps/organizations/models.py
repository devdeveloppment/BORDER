"""Organismes, autorisations formelles, demandes d'accès et base des modèles organisationnels.

Spécification interne non publiée §9.16 (cycle de vie) et §14.3 (dictionnaire des entités).
"""

from __future__ import annotations

import zoneinfo
from typing import Any, ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import TimestampedModel

from .exceptions import CrossTenantWriteError
from .managers import TenantManager
from .tenancy import get_current_tenant

country_code_validator = RegexValidator(r"^[A-Z]{2}$", "Code pays ISO 3166-1 alpha-2 en majuscules attendu.")


def validate_timezone(value: str) -> None:
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f"Fuseau horaire IANA inconnu : {value}")


class OrganizationType(models.TextChoices):
    DOUANE = "douane", "Douane"
    RECETTES = "recettes", "Recettes"
    POLICE = "police", "Police aux frontières"
    PORTUAIRE = "portuaire", "Autorité portuaire"
    TRANSPORT = "transport", "Transport"
    AUTRE = "autre", "Autre"


class OrganizationStatus(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    AUTORISEE = "AUTORISEE", "Autorisée"
    ACTIVE = "ACTIVE", "Active"
    SUSPENDUE = "SUSPENDUE", "Suspendue"
    ARCHIVEE = "ARCHIVEE", "Archivée"


class OrganizationDeploymentMode(models.TextChoices):
    MUTUALISE = "mutualise", "Mutualisé"
    DEDIE = "dedie", "Dédié"


class Organization(TimestampedModel):
    """Organisme autorisé disposant d'un espace isolé.

    Le statut n'est modifié que par les services du cycle de vie (apps.organizations.services),
    réservés au niveau plateforme.
    """

    Type = OrganizationType

    Status = OrganizationStatus

    DeploymentMode = OrganizationDeploymentMode

    name = models.CharField("raison sociale", max_length=200)
    short_name = models.CharField("sigle", max_length=50)
    type = models.CharField("nature", max_length=20, choices=Type.choices)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.EN_ATTENTE)
    country_code = models.CharField("pays", max_length=2, validators=[country_code_validator])
    timezone = models.CharField("fuseau horaire", max_length=64, validators=[validate_timezone])
    retention_days = models.PositiveIntegerField("rétention (jours)", validators=[MinValueValidator(1)])
    deployment_mode = models.CharField(
        "mode d'hébergement", max_length=20, choices=DeploymentMode.choices, default=DeploymentMode.MUTUALISE
    )
    # Données fictives marquées comme telles (§25.1, ADR 0001 · P8).
    is_demo = models.BooleanField("organisme de démonstration", default=False)

    class Meta:
        verbose_name = "organisme"
        verbose_name_plural = "organismes"
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint(Lower("name"), name="organization_name_ci_unique"),
            models.UniqueConstraint(Lower("short_name"), name="organization_short_name_ci_unique"),
            models.CheckConstraint(
                condition=Q(type__in=OrganizationType.values), name="organization_type_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=OrganizationStatus.values), name="organization_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(deployment_mode__in=OrganizationDeploymentMode.values),
                name="organization_deployment_mode_valid",
            ),
            models.CheckConstraint(
                condition=Q(country_code__regex=r"^[A-Z]{2}$"), name="organization_country_iso2"
            ),
            models.CheckConstraint(condition=Q(retention_days__gt=0), name="organization_retention_positive"),
            models.CheckConstraint(condition=~Q(name=""), name="organization_name_not_blank"),
            models.CheckConstraint(condition=~Q(short_name=""), name="organization_short_name_not_blank"),
        )
        indexes = (models.Index(fields=("status",), name="organization_status_idx"),)

    def __str__(self) -> str:
        return self.short_name


class OrganizationAuthorization(TimestampedModel):
    """Trace formelle de l'autorisation d'accès d'un organisme (convention, décision)."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="authorizations")
    reference = models.CharField("référence", max_length=100)
    scope = models.TextField("périmètre autorisé")
    valid_from = models.DateField("début de validité")
    valid_until = models.DateField("fin de validité", null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="enregistrée par"
    )
    # La pièce justificative (§14.3 « document ») sera ajoutée avec le stockage objet applicatif.

    class Meta:
        verbose_name = "autorisation d'organisme"
        verbose_name_plural = "autorisations d'organismes"
        ordering = ("-valid_from",)
        constraints = (
            models.UniqueConstraint(
                fields=("organization", "reference"), name="authorization_reference_unique"
            ),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="authorization_period_valid",
            ),
            models.CheckConstraint(condition=~Q(reference=""), name="authorization_reference_not_blank"),
            models.CheckConstraint(condition=~Q(scope=""), name="authorization_scope_not_blank"),
        )

    def __str__(self) -> str:
        return self.reference


class AccessRequestType(models.TextChoices):
    DEMONSTRATION = "demonstration", "Démonstration"
    ACCES = "acces", "Accès"


class AccessRequestStatus(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    TRAITEE = "TRAITEE", "Traitée"
    REJETEE = "REJETEE", "Rejetée"


class AccessRequest(TimestampedModel):
    """Demande de démonstration ou d'accès (écran 5) : alimente la file du Super Administrateur.

    Aucune création de compte automatique : la demande n'ouvre aucun droit.
    """

    RequestType = AccessRequestType

    Status = AccessRequestStatus

    organization_name = models.CharField("organisme", max_length=200)
    requester_name = models.CharField("nom", max_length=150)
    requester_role = models.CharField("fonction", max_length=150)
    email = models.EmailField("e-mail professionnel")
    phone = models.CharField("téléphone", max_length=30, blank=True)
    request_type = models.CharField("type de demande", max_length=20, choices=RequestType.choices)
    message = models.TextField("message", blank=True)
    consent = models.BooleanField("consentement")
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.EN_ATTENTE)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, null=True, blank=True, related_name="access_requests"
    )
    processed_at = models.DateTimeField("traitée le", null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "demande d'accès"
        verbose_name_plural = "demandes d'accès"
        ordering = ("-created_at",)
        constraints = (
            models.CheckConstraint(condition=Q(consent=True), name="access_request_consent_required"),
            models.CheckConstraint(
                condition=Q(request_type__in=AccessRequestType.values), name="access_request_type_valid"
            ),
            models.CheckConstraint(
                condition=Q(status__in=AccessRequestStatus.values), name="access_request_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(status="EN_ATTENTE", processed_at__isnull=True)
                | (~Q(status="EN_ATTENTE") & Q(processed_at__isnull=False)),
                name="access_request_processing_consistent",
            ),
        )
        indexes = (models.Index(fields=("status", "created_at"), name="access_request_queue_idx"),)

    def __str__(self) -> str:
        return f"{self.organization_name} ({self.get_request_type_display()})"


class TenantScopedModel(TimestampedModel):
    """Base de toute donnée appartenant à un organisme (§12.3, §14.2).

    - ``organization`` NOT NULL, indexé, à placer en tête des index composites des sous-classes ;
    - ``objects`` ne renvoie que les lignes de l'organisme du contexte courant et échoue sans contexte ;
    - l'organisme est attribué depuis le contexte à la création et ne peut jamais être changé ;
    - pas de relation inverse sur Organization (``related_name="+"``) : aucun accès non filtré par ce biais.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="+", editable=False, db_index=True
    )

    objects: ClassVar[TenantManager[Any]] = TenantManager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        context = get_current_tenant()
        if self.organization_id is None:
            self.organization_id = context.organization_id
        elif self.organization_id != context.organization_id:
            raise CrossTenantWriteError("Écriture pour un autre organisme refusée.")
        if not self._state.adding:
            stored = (
                type(self)._base_manager.filter(pk=self.pk).values_list("organization_id", flat=True).first()
            )
            # Ligne absente du périmètre (autre organisme masqué par le RLS) ou inexistante : refus explicite,
            # plutôt que le repli de Django vers un INSERT.
            if stored is None or stored != context.organization_id:
                raise CrossTenantWriteError("Écriture pour un autre organisme refusée.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        context = get_current_tenant()
        if self.organization_id != context.organization_id:
            raise CrossTenantWriteError("Suppression pour un autre organisme refusée.")
        return super().delete(*args, **kwargs)
