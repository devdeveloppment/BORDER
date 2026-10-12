"""Jetons de réinitialisation du mot de passe (écran 8) : lien à usage unique valable 30 minutes.

Basé sur ``PasswordResetTokenGenerator`` (HMAC, horodaté, durée ``PASSWORD_RESET_TIMEOUT``). L'empreinte de
sécurité
entre dans le jeton : dès que le mot de passe est changé (empreinte renouvelée), le jeton devient invalide.
"""

from __future__ import annotations

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.core.db_scope import identity_scope
from apps.users.models import User


class ResetTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "rbi.authentication.tokens.ResetTokenGenerator"
    algorithm = "sha256"

    def _make_hash_value(self, user: User, timestamp: int) -> str:
        return f"{user.pk}{user.password}{user.security_stamp}{user.is_active}{timestamp}"


reset_tokens = ResetTokenGenerator()


def make_reset_token(user: User) -> str:
    return f"{urlsafe_base64_encode(force_bytes(user.pk))}.{reset_tokens.make_token(user)}"


def user_for_reset_token(token: str) -> User | None:
    """Utilisateur actif correspondant à un jeton valide, sinon None (aucune distinction des causes
    d'échec)."""
    try:
        uid_part, token_part = token.split(".", 1)
        uid = force_str(urlsafe_base64_decode(uid_part))
        # Périmètre limité au seul compte désigné par le jeton, le temps de vérifier sa signature HMAC.
        with identity_scope(uid):
            user = User.objects.select_related("organization").get(pk=uid, is_active=True)
    except (ValueError, TypeError, OverflowError, ValidationError, User.DoesNotExist):
        return None
    return user if reset_tokens.check_token(user, token_part) else None
