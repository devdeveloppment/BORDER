"""GeoDjango sur PostGIS : écriture, lecture et fonctions géographiques (coordonnées fictives)."""

from __future__ import annotations

import json

import pytest
from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.db.models.functions import AsGeoJSON, Distance, Transform
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D
from django.db.models.functions import Cast

from tests.gisprobe.models import ProbeSite

pytestmark = pytest.mark.django_db

ORIGIN = Point(0.0, 0.0, srid=4326)


@pytest.fixture
def sites() -> list[ProbeSite]:
    return [
        ProbeSite.objects.create(
            name="Site A", location=Point(0.0, 0.0, srid=4326), area=Polygon.from_bbox((-0.5, -0.5, 0.5, 0.5))
        ),
        ProbeSite.objects.create(name="Site B", location=Point(0.0, 1.0, srid=4326)),
        ProbeSite.objects.create(name="Site C", location=Point(3.0, 0.0, srid=4326)),
    ]


def test_create_and_read_geometry(sites: list[ProbeSite]) -> None:
    stored = ProbeSite.objects.get(pk=sites[1].pk)
    assert stored.location.srid == 4326
    assert (stored.location.x, stored.location.y) == (0.0, 1.0)
    assert stored.area is None
    assert stored.id.version == 4


def test_geodesic_distance(sites: list[ProbeSite]) -> None:
    site_b = ProbeSite.objects.annotate(distance=Distance("location", ORIGIN)).get(name="Site B")
    # Un degré de latitude à l'équateur sur l'ellipsoïde WGS 84 : 110 574 m.
    assert site_b.distance.m == pytest.approx(110_574, abs=5)


def test_dwithin_filter(sites: list[ProbeSite]) -> None:
    near = ProbeSite.objects.filter(location__dwithin=(ORIGIN, D(km=200))).order_by("name")
    assert [site.name for site in near] == ["Site A", "Site B"]


def test_polygon_contains(sites: list[ProbeSite]) -> None:
    inside = ProbeSite.objects.filter(area__contains=Point(0.1, 0.1, srid=4326))
    assert [site.name for site in inside] == ["Site A"]


def test_transform_and_geojson(sites: list[ProbeSite]) -> None:
    # ST_Transform n'accepte que le type geometry : un champ geography doit être converti explicitement.
    as_geometry = Cast("location", GeometryField(srid=4326))
    site_c = ProbeSite.objects.annotate(
        mercator=Transform(as_geometry, 3857), geojson=AsGeoJSON("location")
    ).get(name="Site C")
    # x = 3 * 20 037 508,34 / 180 (Web Mercator)
    assert site_c.mercator.x == pytest.approx(333_958.47, abs=0.1)
    assert json.loads(site_c.geojson) == {"type": "Point", "coordinates": [3, 0]}
