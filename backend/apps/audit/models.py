"""Journal d'audit append-only (§9.11, modèle AuditLog §14 ; ADR 0009).

Les tables sont créées et protégées en SQL par la migration ``audit.0001_initial`` (``managed = False``) :
privilèges par colonne, RLS, scellement par déclencheur (identifiant, horodatage et empreintes calculés par
PostgreSQL), déclencheurs d'immuabilité. Le modèle Django sert à la LECTURE uniquement ; l'écriture passe
exclusivement par ``apps.audit.services.record_event``. Toute tentative de modification ou de suppression par
l'ORM est refusée ici, et l'aurait été par PostgreSQL.

Pas de clé étrangère vers les comptes ni les organismes : l'entrée doit survivre à toute évolution de ces
lignes, et l'écriture autonome (connexion dédiée) ne doit ni attendre ni voir les verrous et lignes non
validées de la transaction métier. Les identifiants sont conservés comme valeurs.
"""

from __future__ import annotations

from typing import Any, NoReturn

from django.db import models


class AppendOnlyError(Exception):
    """Modification ou suppression d'une entrée du journal d'audit : interdite."""


def _refuse(*_: Any, **__: Any) -> NoReturn:
    raise AppendOnlyError("Journal d'audit en insertion seule : modification et suppression interdites.")


class AuditLogQuerySet(models.QuerySet["AuditLog"]):
    update = _refuse
    delete = _refuse
    bulk_create = _refuse
    bulk_update = _refuse
    get_or_create = _refuse
    update_or_create = _refuse
    create = _refuse


class AuditLog(models.Model):
    class Scope(models.TextChoices):
        PLATFORM = "platform", "plateforme"
        ORGANIZATION = "organization", "organisme"

    class ActorType(models.TextChoices):
        USER = "user", "utilisateur"
        ANONYMOUS = "anonymous", "anonyme"
        SYSTEM = "system", "système"

    class Outcome(models.TextChoices):
        SUCCESS = "success", "succès"
        DENIED = "denied", "refus"
        FAILURE = "failure", "échec"

    id = models.BigIntegerField(primary_key=True)
    created_at = models.DateTimeField("horodatage (UTC, serveur PostgreSQL)")
    scope = models.CharField("portée", max_length=20, choices=Scope.choices)
    organization_id = models.UUIDField("organisme concerné", null=True)
    actor_type = models.CharField("type d'acteur", max_length=20, choices=ActorType.choices)
    actor_id = models.UUIDField("acteur", null=True)
    action = models.CharField("action", max_length=64)
    outcome = models.CharField("résultat", max_length=10, choices=Outcome.choices)
    # NULL = « sans objet » : colonnes définies en SQL (migration), distinctes d'une chaîne vide.
    object_type = models.CharField("type d'objet", max_length=40, null=True)  # noqa: DJ001
    object_id = models.CharField("identifiant d'objet", max_length=64, null=True)  # noqa: DJ001
    old_value = models.JSONField("ancienne valeur", null=True)
    new_value = models.JSONField("nouvelle valeur", null=True)
    metadata = models.JSONField("métadonnées")
    ip_address = models.GenericIPAddressField("adresse IP", null=True)
    request_id = models.UUIDField("identifiant de requête", null=True)
    prev_hash = models.CharField("empreinte précédente", max_length=64)
    hash = models.CharField("empreinte", max_length=64)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        managed = False
        db_table = "audit_auditlog"
        ordering = ("id",)
        verbose_name = "entrée du journal d'audit"
        verbose_name_plural = "journal d'audit"

    def __str__(self) -> str:
        return f"#{self.id} {self.action} ({self.outcome})"

    def save(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()


class AuditChain(models.Model):
    """Tête de chaque chaîne (une par organisme, une pour la plateforme), tenue par le déclencheur de
    scellement : dernière entrée, dernière empreinte, longueur. Permet de détecter une troncature de fin de
    chaîne."""

    chain_key = models.CharField(primary_key=True, max_length=64)
    last_id = models.BigIntegerField(null=True)
    last_hash = models.CharField(max_length=64)
    length = models.BigIntegerField()
    updated_at = models.DateTimeField(null=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        managed = False
        db_table = "audit_chain"

    def __str__(self) -> str:
        return f"{self.chain_key} ({self.length})"

    def save(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        _refuse()
