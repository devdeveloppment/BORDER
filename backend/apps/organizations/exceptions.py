"""Erreurs du cloisonnement organisationnel.

Les messages sont destinés aux journaux : l'API (P2.8) les traduira en 403/404 génériques,
sans révéler l'existence ni le contenu d'une ressource d'un autre organisme.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied


class TenantContextMissing(RuntimeError):
    """Aucun contexte d'organisme : erreur de programmation ou tentative d'accès hors périmètre."""


class TenantAccessDenied(PermissionDenied):
    """L'identité ne donne pas accès à un espace organisationnel (compte plateforme, organisme non actif…)."""


class CrossTenantWriteError(PermissionDenied):
    """Écriture visant un autre organisme que celui du contexte courant."""


class PlatformAccessDenied(PermissionDenied):
    """Opération globale (niveau plateforme) non autorisée pour cet acteur."""


class InvalidTransition(ValueError):
    """Changement de statut d'organisme non prévu par le cycle de vie (§9.16)."""
