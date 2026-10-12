from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

if TYPE_CHECKING:
    from .models import User


class UserManager(BaseUserManager["User"]):
    """Création technique d'un compte identifié par son e-mail (normalisé en minuscules).

    N'attribue aucun droit : les rôles passent par apps.users.services. Pas de ``create_superuser`` :
    le premier Super Administrateur se crée avec la commande ``create_super_admin``.
    """

    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> User:
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
