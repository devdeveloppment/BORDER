"""Limitation des tentatives (§19.1 « rate limiting », écrans 6 et 7 « verrouillage après 5 échecs »).

Compteurs dans Redis (cache Django), clés dérivées d'un HMAC de l'identifiant : aucun e-mail ni adresse IP
en clair
dans Redis. Les règles s'appliquent de la même façon qu'un compte existe ou non : elles ne révèlent rien.

- Connexion, par identifiant soumis : 5 échecs → verrouillage progressif (1, 2, 4… minutes, plafonné à 60).
- Connexion, par adresse IP : 30 échecs sur 15 minutes → refus temporaire.
- MFA, par compte : 5 codes invalides → verrouillage de 15 minutes et retour à l'étape mot de passe.
- Réinitialisation, par identifiant (3/heure) et par IP (20/heure) : au-delà, réponse identique mais aucun
  envoi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from django.core.cache import BaseCache, caches
from django.http import HttpRequest
from django.utils.crypto import salted_hmac

from apps.core.client_ip import client_ip as resolved_client_ip

LOGIN_FAILURES_BEFORE_LOCK = 5
LOGIN_FAILURE_WINDOW = 60 * 60
LOGIN_LOCK_BASE = 60
LOGIN_LOCK_MAX = 60 * 60
IP_FAILURES_LIMIT = 30
IP_FAILURE_WINDOW = 15 * 60
MFA_FAILURES_BEFORE_LOCK = 5
MFA_LOCK = 15 * 60
RESET_PER_IDENTIFIER = (3, 60 * 60)
RESET_PER_IP = (20, 60 * 60)


def _cache() -> BaseCache:
    return caches["default"]


def _key(kind: str, identifier: str) -> str:
    digest = salted_hmac(
        "rbi.authentication.throttling", identifier.strip().lower(), algorithm="sha256"
    ).hexdigest()
    return f"auth:{kind}:{digest}"


def client_ip(request: HttpRequest) -> str:
    """Adresse cliente selon la politique unique du proxy de confiance (``apps.core.client_ip``, P2.10)."""
    return resolved_client_ip(request) or "unknown"


@dataclass(frozen=True, slots=True)
class Lock:
    retry_after: int


def _increment(key: str, window: int) -> int:
    cache = _cache()
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return int(cache.incr(key))
    except ValueError:  # expirée entre add et incr
        cache.set(key, 1, timeout=window)
        return 1


def _set_lock(key: str, duration: int) -> None:
    """Le verrou stocke son instant d'expiration (le cache Redis de Django n'expose pas le TTL)."""
    _cache().set(key, time.time() + duration, timeout=duration)


def _lock_remaining(key: str) -> Lock | None:
    expires_at = _cache().get(key)
    if expires_at is None:
        return None
    remaining = int(float(expires_at) - time.time()) + 1
    return Lock(retry_after=remaining) if remaining > 0 else None


# --- Connexion ------------------------------------------------------------------------------


def login_lock(identifier: str, ip: str) -> Lock | None:
    lock = _lock_remaining(_key("login-lock", identifier))
    if lock:
        return lock
    failures = _cache().get(_key("login-ip", ip))
    if failures is not None and int(failures) >= IP_FAILURES_LIMIT:
        return Lock(retry_after=IP_FAILURE_WINDOW)
    return None


def register_login_failure(identifier: str, ip: str) -> None:
    _increment(_key("login-ip", ip), IP_FAILURE_WINDOW)
    failures = _increment(_key("login-fail", identifier), LOGIN_FAILURE_WINDOW)
    if failures >= LOGIN_FAILURES_BEFORE_LOCK:
        duration = min(LOGIN_LOCK_BASE * 2 ** (failures - LOGIN_FAILURES_BEFORE_LOCK), LOGIN_LOCK_MAX)
        _set_lock(_key("login-lock", identifier), duration)


def reset_login_failures(identifier: str) -> None:
    _cache().delete_many([_key("login-fail", identifier), _key("login-lock", identifier)])


# --- MFA ---------------------------------------------------------------------------------------


def mfa_lock(user_id: str) -> Lock | None:
    return _lock_remaining(_key("mfa-lock", user_id))


def register_mfa_failure(user_id: str) -> bool:
    """Renvoie True si le compte vient d'être verrouillé."""
    failures = _increment(_key("mfa-fail", user_id), MFA_LOCK)
    if failures >= MFA_FAILURES_BEFORE_LOCK:
        _set_lock(_key("mfa-lock", user_id), MFA_LOCK)
        _cache().delete(_key("mfa-fail", user_id))
        return True
    return False


def reset_mfa_failures(user_id: str) -> None:
    _cache().delete(_key("mfa-fail", user_id))


# --- Réinitialisation du mot de passe ----------------------------------------------------------


def allow_password_reset(identifier: str, ip: str) -> bool:
    per_id = _increment(_key("reset-id", identifier), RESET_PER_IDENTIFIER[1])
    per_ip = _increment(_key("reset-ip", ip), RESET_PER_IP[1])
    return per_id <= RESET_PER_IDENTIFIER[0] and per_ip <= RESET_PER_IP[0]
