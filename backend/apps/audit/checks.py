"""Contrôle système : l'écriture autonome du journal d'audit est obligatoire hors tests (ADR 0009)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, register


@register()
def audit_write_mode(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    mode = getattr(settings, "RBI_AUDIT_WRITE_MODE", "autonomous")
    if mode not in ("autonomous", "inline"):
        return [Error(f"RBI_AUDIT_WRITE_MODE inconnu : {mode!r}", id="rbi.E002")]
    if mode == "inline" and getattr(settings, "RBI_ENV", "production") != "test":
        return [
            Error(
                "RBI_AUDIT_WRITE_MODE='inline' est réservé aux tests : un refus ou un échec serait perdu "
                "avec l'annulation de la transaction métier.",
                id="rbi.E001",
            )
        ]
    return []
