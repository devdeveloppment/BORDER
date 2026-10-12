"""Backend d'authentification RBI (identifiant : e-mail, §14.3).

- ``authenticate`` : vérifie e-mail + mot de passe (hachage Argon2), avec un hachage factice pour un e-mail
  inconnu, afin de ne pas révéler l'existence d'un compte par le temps de réponse (comme ``ModelBackend``).
- ``get_user`` : appelé à CHAQUE requête pour reconstruire l'identité depuis la base. Un compte désactivé, ou
  dont l'organisme n'est plus ACTIVE (suspension, archivage), perd immédiatement sa session.
- P2.6 : la recherche par e-mail s'exécute dans un périmètre ``app.auth_email`` (seuls ce compte et son
  organisme sont visibles) ; la restauration de session, dans le périmètre du seul compte de la session
  (identifiant conservé côté serveur, jamais fourni par le client).
- Aucune permission Django : ``has_perm`` & co. renvoient toujours « non ». L'autorisation passe exclusivement
  par le RBAC (apps.users.rbac).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from apps.core.db_scope import db_scope, identity_scope
from apps.users.models import User


def account_usable(user: User) -> bool:
    """Compte utilisable maintenant : actif, et organisme ACTIVE pour un compte organisationnel."""
    if not user.is_active:
        return False
    if user.organization_id is None:
        return True
    from apps.organizations.models import Organization

    return user.organization is not None and user.organization.status == Organization.Status.ACTIVE


class RBIAuthBackend(ModelBackend):
    def authenticate(  # type: ignore[override]
        self,
        request: HttpRequest | None,
        email: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        if not email or password is None:
            return None
        with db_scope(current_user="", current_org="", auth_email=email, platform=""):
            user = User.objects.select_related("organization").filter(email=email.strip().lower()).first()
        if user is None:
            User().set_password(password)  # coût de hachage identique pour un compte inexistant
            return None
        with identity_scope(user.pk):  # check_password peut ré-enregistrer un hachage mis à niveau
            valid = user.check_password(password)
        if valid and user.is_active:
            return user
        return None

    def get_user(self, user_id: Any) -> User | None:
        try:
            with identity_scope(user_id):
                user = User.objects.select_related("organization").get(pk=user_id)
        except (User.DoesNotExist, ValueError):
            return None
        return user if account_usable(user) else None

    # --- Aucune permission Django (P2.4 : RBAC uniquement) -------------------------------------

    def get_user_permissions(self, user_obj: Any, obj: Any = None) -> set[str]:
        return set()

    def get_group_permissions(self, user_obj: Any, obj: Any = None) -> set[str]:
        return set()

    def get_all_permissions(self, user_obj: Any, obj: Any = None) -> set[str]:
        return set()

    def has_perm(self, user_obj: Any, perm: str, obj: Any = None) -> bool:
        return False

    def has_module_perms(self, user_obj: Any, app_label: str) -> bool:
        return False
