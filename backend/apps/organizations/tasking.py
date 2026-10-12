"""Contexte d'organisme des tâches asynchrones.

Une tâche portant sur des données d'un organisme reçoit son ``organization_id`` en argument nommé explicite ;
``tenant_task`` le vérifie (organisme existant et ACTIVE), pose le contexte pendant l'exécution et le retire
ensuite. Le worker n'hérite jamais d'un contexte : sans ``organization_id``, la tâche échoue.

Exemple (lorsque les modules métier existeront) :

    @shared_task
    @tenant_task
    def recompute_indicators(*, organization_id: str, post_id: str) -> None: ...

    recompute_indicators.delay(organization_id=str(context.organization_id), post_id=str(post.pk))
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from .tenancy import context_for_task, tenant_context


def tenant_task[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        context = context_for_task(kwargs.get("organization_id"))  # type: ignore[arg-type]
        with tenant_context(context):
            return func(*args, **kwargs)

    return wrapper
