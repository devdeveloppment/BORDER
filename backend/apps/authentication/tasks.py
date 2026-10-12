"""Tâches asynchrones de l'authentification.

Envoi du lien de réinitialisation hors du cycle de la requête : la réponse à « mot de passe oublié » ne
dépend plus du temps d'envoi SMTP, qui révélait l'existence d'un compte. La requête
programme TOUJOURS exactement une tâche ; pour un compte inexistant, inutilisable ou une demande limitée,
la tâche ne reçoit aucun identifiant et ne fait rien.

Le broker ne transporte que l'identifiant du compte : le jeton est produit par le worker, dans le périmètre
PostgreSQL de ce seul compte (P2.6), au moment de l'envoi. Aucun résultat n'est conservé.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail

from apps.core.db_scope import identity_scope
from apps.users.models import User

from .backends import account_usable
from .tokens import make_reset_token

logger = logging.getLogger(__name__)


@shared_task(name="auth.password_reset.send", ignore_result=True)
def send_password_reset_email(user_id: str | None = None) -> None:
    if not user_id:
        return
    try:
        with identity_scope(user_id):
            user = User.objects.select_related("organization").filter(pk=user_id).first()
    except (ValueError, ValidationError):
        user = None
    if user is None or not account_usable(user):  # désactivé ou suspendu entre la demande et l'envoi
        logger.info("Lien de réinitialisation non envoyé : compte inutilisable.")
        return
    link = f"{settings.RBI_FRONTEND_URL}/connexion/recuperation?token={make_reset_token(user)}"
    send_mail(
        subject="RBI — Réinitialisation de votre mot de passe",
        message=(
            "Une réinitialisation de mot de passe a été demandée pour votre compte RBI.\n\n"
            f"Lien à usage unique, valable 30 minutes :\n{link}\n\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )
