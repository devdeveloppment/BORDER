"""Vérifications statiques du journal d'audit (P2.7) : une seule voie d'écriture, catalogue exact, mode
imposé."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from apps.audit.catalog import ACTIONS
from apps.audit.checks import audit_write_mode

APPS = Path(__file__).resolve().parents[2]


def _sources() -> list[Path]:
    return [
        path for path in APPS.rglob("*.py") if "tests" not in path.parts and "migrations" not in path.parts
    ]


def test_only_the_writer_inserts_into_the_journal() -> None:
    offenders = [
        str(path.relative_to(APPS))
        for path in _sources()
        if "INSERT INTO audit_auditlog" in path.read_text(encoding="utf-8") and path.name != "writer.py"
    ]
    assert offenders == []


def _record_event_calls() -> tuple[set[str], list[str]]:
    literals: set[str] = set()
    dynamic: list[str] = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            # record_event, et _deny (apps/users/services.py) qui lui transmet l'action reçue.
            if not (
                isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("record_event", "_deny")
            ):
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                literals.add(first.value)
            elif isinstance(first, ast.IfExp):
                literals |= {
                    b.value
                    for b in (first.body, first.orelse)
                    if isinstance(b, ast.Constant) and isinstance(b.value, str)
                }
            else:
                dynamic.append(f"{path.relative_to(APPS)}:{node.lineno}")
    return literals, dynamic


def test_every_recorded_action_is_in_the_catalog() -> None:
    literals, dynamic = _record_event_calls()
    assert literals <= set(ACTIONS), literals - set(ACTIONS)
    # Appels à action calculée, tous connus : organization.{activate|reactivate} et le relais _deny.
    assert sorted(d.split(":")[0] for d in dynamic) == ["organizations/services.py", "users/services.py"], (
        dynamic
    )


def test_catalog_declares_no_unused_event() -> None:
    """Aucun événement inventé : chaque action du catalogue est réellement produite par le code."""
    literals, _ = _record_event_calls()
    produced = literals | {"organization.activate", "organization.reactivate"}
    assert set(ACTIONS) == produced, set(ACTIONS) ^ produced


def test_inline_mode_is_refused_outside_tests(settings: Any) -> None:
    settings.RBI_AUDIT_WRITE_MODE = "inline"
    settings.RBI_ENV = "production"
    assert [error.id for error in audit_write_mode()] == ["rbi.E001"]
    settings.RBI_AUDIT_WRITE_MODE = "autre"
    assert [error.id for error in audit_write_mode()] == ["rbi.E002"]
    settings.RBI_ENV = "test"
    settings.RBI_AUDIT_WRITE_MODE = "inline"
    assert audit_write_mode() == []


def test_production_default_is_autonomous() -> None:
    from config.settings import base

    assert base.RBI_AUDIT_WRITE_MODE == "autonomous"
    # Le proxy de confiance (P2.10) passe en premier ; le contexte de requête vient juste après.
    assert base.MIDDLEWARE[0] == "apps.core.client_ip.TrustedProxyMiddleware"
    assert base.MIDDLEWARE.index("apps.core.request_context.RequestContextMiddleware") == 1
