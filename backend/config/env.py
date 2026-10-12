"""Lecture typée des variables d'environnement.

Aucun secret n'a de valeur par défaut : une variable obligatoire absente arrête le démarrage
avec un message explicite (ImproperlyConfigured), plutôt que de fonctionner avec une valeur faible.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def env_str(name: str, default: str | None = None) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            raise ImproperlyConfigured(f"Variable d'environnement obligatoire absente : {name}")
        return default
    return value


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ImproperlyConfigured(f"{name} doit être un booléen (true/false), reçu : {value!r}")


def env_int(name: str, default: int | None = None) -> int:
    raw = env_str(name, None if default is None else str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} doit être un entier, reçu : {raw!r}") from exc


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        if default is None:
            raise ImproperlyConfigured(f"Variable d'environnement obligatoire absente : {name}")
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]
