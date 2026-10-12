"""Modèles abstraits communs (conventions §14.2)."""

from __future__ import annotations

import uuid

from django.db import models


class UUIDPrimaryKeyModel(models.Model):
    """Clé primaire UUID v4, non devinable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(UUIDPrimaryKeyModel):
    """Horodatages UTC (timestamptz) de création et de dernière modification."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
