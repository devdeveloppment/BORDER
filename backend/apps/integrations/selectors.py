"""Lectures des sources de données : toujours dans le contexte d'organisme courant."""

from __future__ import annotations

import uuid

from django.db.models import QuerySet

from .models import DataSource


def list_data_sources() -> QuerySet[DataSource]:
    return DataSource.objects.all()


def get_data_source(data_source_id: uuid.UUID) -> DataSource:
    """Lève ``DataSource.DoesNotExist`` pour un identifiant inconnu OU appartenant à un autre organisme :
    les deux cas sont indiscernables (404 côté API, aucun contenu révélé)."""
    data_source: DataSource = DataSource.objects.get(pk=data_source_id)
    return data_source
