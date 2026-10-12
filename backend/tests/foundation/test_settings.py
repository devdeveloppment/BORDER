"""Configuration Django : chargée depuis l'environnement, sûre par défaut, sans secret dans le code."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config import env as env_module


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - interpréteur courant, arguments constants
        [sys.executable, *args], env=env, capture_output=True, text=True, timeout=120, check=False
    )


def test_settings_come_from_environment() -> None:
    """Chargement dans un processus neuf : pytest-django renomme la base dans le processus courant."""
    code = (
        "import json, django; django.setup(); from django.conf import settings as s; "
        "db = s.DATABASES['default']; "
        "print(json.dumps([s.SECRET_KEY, db['HOST'], db['PORT'], db['NAME'], db['USER'], db['PASSWORD'], "
        "s.CELERY_BROKER_URL, s.CELERY_RESULT_BACKEND, s.CACHES['default']['LOCATION']]))"
    )
    result = _run(["-c", code], {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.development"})
    assert result.returncode == 0, result.stderr
    names = [
        "RBI_DJANGO_SECRET_KEY",
        "RBI_DB_HOST",
        "RBI_DB_PORT",
        "RBI_DB_NAME",
        "RBI_DB_USER",
        "RBI_DB_PASSWORD",
        "RBI_CELERY_BROKER_URL",
        "RBI_CELERY_RESULT_BACKEND",
        "RBI_CACHE_URL",
    ]
    expected: list[object] = [os.environ[name] for name in names]
    expected[2] = int(os.environ["RBI_DB_PORT"])
    assert json.loads(result.stdout) == expected
    assert len(os.environ["RBI_DJANGO_SECRET_KEY"]) >= 32


def test_test_settings_are_safe() -> None:
    assert settings.RBI_ENV == "test"
    assert settings.DEBUG is False
    assert settings.DATABASES["default"]["ENGINE"] == "django.contrib.gis.db.backends.postgis"
    assert settings.AUTH_USER_MODEL == "users.User"
    assert settings.CELERY_ACCEPT_CONTENT == ["json"]
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Strict"


def test_required_variable_missing_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RBI_DJANGO_SECRET_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured, match="RBI_DJANGO_SECRET_KEY"):
        env_module.env_str("RBI_DJANGO_SECRET_KEY")


def test_invalid_boolean_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RBI_TEST_FLAG", "peut-être")
    with pytest.raises(ImproperlyConfigured):
        env_module.env_bool("RBI_TEST_FLAG", False)


@pytest.mark.parametrize("module", ["config.settings.development", "config.settings.test"])
def test_django_refuses_to_start_without_secret_key(module: str) -> None:
    env = {k: v for k, v in os.environ.items() if k != "RBI_DJANGO_SECRET_KEY"}
    env["DJANGO_SETTINGS_MODULE"] = module
    result = _run(["-c", "import django; django.setup()"], env)
    assert result.returncode != 0
    assert "RBI_DJANGO_SECRET_KEY" in result.stderr


def test_base_settings_default_to_production_without_debug() -> None:
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.base"}
    env.pop("RBI_DJANGO_DEBUG", None)
    env.pop("RBI_ENV", None)
    code = (
        "import django; django.setup(); from django.conf import settings as s; "
        "print(s.RBI_ENV, s.DEBUG, s.ALLOWED_HOSTS, s.SESSION_COOKIE_SECURE)"
    )
    result = _run(["-c", code], env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "production False [] True"


@pytest.mark.parametrize("module", ["config.settings.development", "config.settings.test"])
def test_django_system_checks_pass(module: str) -> None:
    result = _run(
        ["manage.py", "check", "--fail-level", "WARNING"], {**os.environ, "DJANGO_SETTINGS_MODULE": module}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no issues" in result.stdout


def test_modular_apps_are_registered() -> None:
    from django.apps import apps

    expected = {
        "core",
        "health",
        "authentication",
        "organizations",
        "users",
        "border_posts",
        "activities",
        "vehicles",
        "events",
        "alerts",
        "analytics",
        "risk_engine",
        "reports",
        "notifications",
        "audit",
        "integrations",
    }
    labels = {config.label for config in apps.get_app_configs()}
    assert expected <= labels
    for label in expected:
        assert apps.get_app_config(label).name == f"apps.{label}"
