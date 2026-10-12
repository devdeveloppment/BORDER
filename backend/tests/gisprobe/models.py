from django.contrib.gis.db import models

from apps.core.models import TimestampedModel


class ProbeSite(TimestampedModel):
    """Site fictif : point géographique (géodésique, WGS 84) et zone optionnelle."""

    name = models.CharField(max_length=100)
    location = models.PointField(geography=True, srid=4326)
    area = models.PolygonField(srid=4326, null=True, blank=True)

    def __str__(self) -> str:
        return self.name
