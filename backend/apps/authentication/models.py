"""Codes de secours MFA (écran 7 « code de secours »).

Stockés sous forme d'empreinte HMAC-SHA256 (jamais en clair) et à usage unique. Les codes ont ~50 bits
d'entropie
(10 caractères sur un alphabet de 32 symboles) : un HMAC suffit, sans hachage lent.
Les secrets TOTP sont gérés par django-otp (``otp_totp_totpdevice``) ; leur chiffrement au repos est prévu
en V1 (§19.1).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class MfaBackupCode(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_backup_codes"
    )
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "authentication_mfa_backup_code"
        constraints = (models.UniqueConstraint(fields=("user", "code_hash"), name="mfa_backup_code_unique"),)

    def __str__(self) -> str:
        return f"code de secours de {self.user_id}"
