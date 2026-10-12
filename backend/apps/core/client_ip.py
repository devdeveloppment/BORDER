"""Adresse cliente d'une requête : politique unique pour l'authentification, DRF, la limitation de débit et le
journal d'audit (P2.10, ADR 0012).

Règles :

1. Sans proxy de confiance déclaré (``RBI_TRUSTED_PROXIES`` vide), l'adresse est celle du pair TCP
   (``REMOTE_ADDR``). ``X-Forwarded-For`` est ignoré.
2. ``X-Forwarded-For`` n'est lu QUE si le pair TCP est un proxy déclaré. Les entrées sont parcourues de
   droite à
   gauche ; les proxys déclarés sont ignorés ; la première adresse non déclarée est l'adresse cliente. Nginx
   (``infra/nginx``) REMPLACE l'en-tête par l'adresse de son propre pair : une valeur envoyée par le
   navigateur
   n'atteint jamais l'application.
3. Échec sûr : un en-tête absent, vide ou illisible derrière un proxy déclaré donne l'adresse du proxy (jamais
   une valeur invérifiable) et produit un avertissement dans les journaux du serveur (proxy mal configuré).
4. Configuration vérifiée au démarrage (``trusted_networks``) : une entrée illisible, ou un réseau qui
   couvrirait
   des clients quelconques (préfixe plus large que /16 en IPv4 ou /48 en IPv6, dont ``0.0.0.0/0``), arrête
   l'application (``ImproperlyConfigured``).

Le contexte d'organisme ne dépend d'aucun en-tête (P2.3, P2.6) : cette adresse sert à la limitation de débit
et
à la traçabilité, jamais à une décision d'autorisation.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Address = ipaddress.IPv4Address | ipaddress.IPv6Address

MIN_PREFIX = {4: 16, 6: 48}
FORWARDED_FOR = "HTTP_X_FORWARDED_FOR"


def parse_trusted_proxies(entries: Iterable[str]) -> tuple[Network, ...]:
    """Réseaux de confiance validés ; toute entrée douteuse est une erreur de configuration."""
    networks: list[Network] = []
    for raw in entries:
        entry = raw.strip()
        try:
            network = ipaddress.ip_network(entry, strict=True)
        except ValueError as exc:
            raise ImproperlyConfigured(f"RBI_TRUSTED_PROXIES : entrée invalide {entry!r}.") from exc
        if network.prefixlen < MIN_PREFIX[network.version]:
            raise ImproperlyConfigured(
                f"RBI_TRUSTED_PROXIES : réseau trop large {entry!r} (au plus /{MIN_PREFIX[network.version]})."
            )
        networks.append(network)
    return tuple(networks)


@lru_cache(maxsize=1)
def trusted_networks() -> tuple[Network, ...]:
    return parse_trusted_proxies(getattr(settings, "RBI_TRUSTED_PROXIES", ()))


def _address(value: object) -> Address | None:
    try:
        return ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None


def is_trusted_proxy(address: Address | None, networks: tuple[Network, ...] | None = None) -> bool:
    if address is None:
        return False
    return any(address in network for network in (trusted_networks() if networks is None else networks))


def resolve_client_ip(
    remote_addr: object, forwarded_for: object, networks: tuple[Network, ...] | None = None
) -> str | None:
    """Fonction pure (testée seule) : adresse cliente selon la politique ci-dessus, ``None`` si illisible."""
    peer = _address(remote_addr)
    if peer is None:
        return None
    if not is_trusted_proxy(peer, networks):
        return str(peer)
    entries = [item.strip() for item in str(forwarded_for or "").split(",") if item.strip()]
    for item in reversed(entries):
        candidate = _address(item)
        if candidate is None:
            break  # entrée illisible : on ne remonte pas au-delà d'une valeur invérifiable
        if not is_trusted_proxy(candidate, networks):
            return str(candidate)
    logger.warning("Proxy de confiance sans X-Forwarded-For exploitable : adresse du proxy retenue.")
    return str(peer)


def client_ip(request: Any) -> str | None:
    """Adresse cliente de la requête (calculée une fois, mémorisée sur la requête)."""
    cached = getattr(request, "_rbi_client_ip", ...)
    if cached is not ...:
        return cached  # type: ignore[no-any-return]
    meta = getattr(request, "META", {})
    value = resolve_client_ip(meta.get("REMOTE_ADDR"), meta.get(FORWARDED_FOR))
    with contextlib.suppress(AttributeError):  # objet de requête figé (tests) : pas de mémorisation
        request._rbi_client_ip = value
    return value


class TrustedProxyMiddleware:
    """Premier middleware : les en-têtes de transfert ne sont conservés que s'ils viennent du proxy déclaré.

    ``X-Forwarded-Proto`` (HTTPS derrière le proxy, ``SECURE_PROXY_SSL_HEADER``) et ``X-Forwarded-For`` reçus
    d'un autre pair sont SUPPRIMÉS avant tout traitement : Django ne peut pas croire à tort qu'une requête est
    en HTTPS, et aucun composant ne peut lire une adresse forgée.
    """

    STRIPPED = ("HTTP_X_FORWARDED_PROTO", FORWARDED_FOR, "HTTP_X_FORWARDED_HOST", "HTTP_FORWARDED")

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        if not is_trusted_proxy(_address(request.META.get("REMOTE_ADDR"))):
            for name in self.STRIPPED:
                request.META.pop(name, None)
        else:
            request.META.pop("HTTP_X_FORWARDED_HOST", None)  # jamais utilisé (USE_X_FORWARDED_HOST = False)
            request.META.pop("HTTP_FORWARDED", None)
        client_ip(request)
        return self.get_response(request)
