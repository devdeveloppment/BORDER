"""Image backend : versions de la stack (§13) et bibliothèques géospatiales chargeables."""

from __future__ import annotations

import os
import sys
from importlib.metadata import version


def test_python_version() -> None:
    assert sys.version_info >= (3, 12)


def test_stack_versions() -> None:
    assert version("django").startswith("5.2.")
    assert version("djangorestframework").startswith("3.17.")
    assert version("celery").startswith("5.")
    assert version("django-celery-beat").split(".")[0] == "2"
    assert version("drf-spectacular").startswith("0.")
    assert version("psycopg").startswith("3.")


def test_geodjango_libraries_load() -> None:
    from django.conf import settings

    if not settings.configured:
        settings.configure()
    from django.contrib.gis.gdal import gdal_version
    from django.contrib.gis.geos import Point, geos_version

    assert gdal_version().decode().startswith("3.")
    assert geos_version().decode().startswith("3.")
    point = Point(2.35, 48.85, srid=4326)
    point.transform(3857)
    # x = 2,35 * 20 037 508,34 / 180 (Web Mercator)
    assert abs(point.x - 261_600.80) < 0.01


def test_runs_as_non_root() -> None:
    assert os.getuid() != 0
