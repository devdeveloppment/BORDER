"""Second facteur : TOTP (django-otp, RFC 6238) et codes de secours.

- Enrôlement : un appareil TOTP non confirmé est créé ; il n'est confirmé qu'après un premier code valide.
- Vérification : tolérance d'un pas de 30 s ; un code déjà accepté ne peut pas être rejoué (``last_t`` de
  django-otp) ; un code trop ancien est refusé (« expiré ») ; django-otp ajoute son propre ralentissement
  exponentiel.
- Renouvellement : le nouvel appareil remplace l'ancien seulement une fois confirmé.
- P2.6 : toutes les opérations s'exécutent dans le périmètre PostgreSQL du seul compte concerné : le RLS rend
  invisibles les secrets de tout autre compte.
- Codes de secours : 10 codes à usage unique, régénérés à l'enrôlement et sur demande (les anciens sont
  révoqués).
"""

from __future__ import annotations

import secrets

from django.utils import timezone
from django.utils.crypto import salted_hmac
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.db_scope import identity_scope
from apps.users.models import User
from apps.users.rbac import requires_mfa

from .models import MfaBackupCode

BACKUP_CODE_COUNT = 10
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O ni 1/I


def confirmed_device(user: User) -> TOTPDevice | None:
    with identity_scope(user.pk):
        return TOTPDevice.objects.filter(user=user, confirmed=True).order_by("-id").first()


def pending_device(user: User) -> TOTPDevice | None:
    with identity_scope(user.pk):
        return TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-id").first()


def mfa_enabled(user: User) -> bool:
    with identity_scope(user.pk):
        return bool(TOTPDevice.objects.filter(user=user, confirmed=True).exists())


def mfa_needed(user: User) -> bool:
    """MFA exigée par un rôle (§9.12) ou activée volontairement par l'utilisateur."""
    return requires_mfa(user) or mfa_enabled(user)


def start_totp_enrollment(user: User) -> TOTPDevice:
    """Nouvel appareil non confirmé (remplace un enrôlement inachevé)."""
    with identity_scope(user.pk):
        TOTPDevice.objects.filter(user=user, confirmed=False).delete()
        return TOTPDevice.objects.create(user=user, name="RBI", confirmed=False)


def provisioning(device: TOTPDevice) -> dict[str, str]:
    """URI otpauth:// (QR code côté client) et secret base32 pour la saisie manuelle. Affichés une seule
    fois."""
    from base64 import b32encode

    return {"otpauth_uri": device.config_url, "secret": b32encode(device.bin_key).decode().rstrip("=")}


def verify_totp(device: TOTPDevice | None, code: str) -> bool:
    if device is None or not (len(code) == 6 and code.isdigit()):
        return False
    with identity_scope(device.user_id):  # verify_token enregistre last_t (anti-rejeu) et le ralentissement
        return bool(device.verify_token(code))


def confirm_device(device: TOTPDevice) -> None:
    """Confirme l'appareil et révoque tout autre appareil de l'utilisateur."""
    with identity_scope(device.user_id):
        TOTPDevice.objects.filter(user_id=device.user_id).exclude(pk=device.pk).delete()
        device.confirmed = True
        device.save(update_fields=["confirmed"])


def _hash(code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").upper()
    return salted_hmac("rbi.authentication.backup_code", normalized, algorithm="sha256").hexdigest()


def generate_backup_codes(user: User) -> list[str]:
    codes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    with identity_scope(user.pk):
        MfaBackupCode.objects.filter(user=user).delete()
        MfaBackupCode.objects.bulk_create(MfaBackupCode(user=user, code_hash=_hash(code)) for code in codes)
    return codes


def use_backup_code(user: User, code: str) -> bool:
    """Consomme un code de secours (mise à jour atomique : un code ne sert qu'une fois, même en
    concurrence)."""
    if not (8 <= len(code) <= 20):
        return False
    with identity_scope(user.pk):
        used = MfaBackupCode.objects.filter(user=user, code_hash=_hash(code), used_at__isnull=True).update(
            used_at=timezone.now()
        )
    return used == 1


def remaining_backup_codes(user: User) -> int:
    with identity_scope(user.pk):
        return MfaBackupCode.objects.filter(user=user, used_at__isnull=True).count()


def remove_mfa(user: User) -> None:
    """Supprime tous les facteurs DU COMPTE DU PÉRIMÈTRE (désactivation volontaire, commande serveur).
    La réinitialisation par un administrateur passe par la fonction SQL ``rbi_admin_reset_mfa``."""
    with identity_scope(user.pk):
        TOTPDevice.objects.filter(user=user).delete()
        MfaBackupCode.objects.filter(user=user).delete()
