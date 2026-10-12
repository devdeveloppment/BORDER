"""Gestionnaires des modèles organisationnels : filtrage automatique par organisme, fermé par défaut."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, TypeVar

from django.db import models

from .exceptions import CrossTenantWriteError
from .tenancy import get_current_tenant

if TYPE_CHECKING:
    from .models import TenantScopedModel

_M = TypeVar("_M", bound="TenantScopedModel")

_ORGANIZATION_FIELDS = {"organization", "organization_id"}


class TenantQuerySet(models.QuerySet[_M]):
    def update(self, **kwargs: Any) -> int:
        if _ORGANIZATION_FIELDS & kwargs.keys():
            raise CrossTenantWriteError(
                "Le rattachement d'une donnée à son organisme ne peut pas être modifié."
            )
        return super().update(**kwargs)

    def bulk_create(self, objs: Iterable[_M], *args: Any, **kwargs: Any) -> list[_M]:
        context = get_current_tenant()
        objs = list(objs)
        for obj in objs:
            if obj.organization_id is None:
                obj.organization_id = context.organization_id
            elif obj.organization_id != context.organization_id:
                raise CrossTenantWriteError("Création pour un autre organisme refusée.")
        return super().bulk_create(objs, *args, **kwargs)

    def bulk_update(self, objs: Iterable[_M], fields: Iterable[str], *args: Any, **kwargs: Any) -> int:
        fields = list(fields)
        if _ORGANIZATION_FIELDS & set(fields):
            raise CrossTenantWriteError(
                "Le rattachement d'une donnée à son organisme ne peut pas être modifié."
            )
        return super().bulk_update(objs, fields, *args, **kwargs)


class TenantManager(models.Manager[_M]):
    """Gestionnaire par défaut : ne renvoie QUE les lignes de l'organisme du contexte courant.

    Sans contexte, ``get_queryset`` lève ``TenantContextMissing`` : un oubli produit une erreur visible,
    jamais une fuite. Les mécanismes internes de Django (suppressions en cascade, migrations) utilisent
    ``_base_manager``, non filtré, qui n'est pas exposé au code applicatif.
    """

    _queryset_class = TenantQuerySet

    def get_queryset(self) -> TenantQuerySet[_M]:
        context = get_current_tenant()
        return TenantQuerySet(self.model, using=self._db).filter(organization_id=context.organization_id)
