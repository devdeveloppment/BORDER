"""Parcours d'authentification (écrans 6, 7, 8 et 29 ; §19.1).

États d'une session :
1. **anonyme** ;
2. **en attente de MFA** : mot de passe vérifié, mais AUCUNE connexion Django. La session porte seulement
   ``PENDING_KEY`` (utilisateur, étape, horodatage, empreinte de sécurité), valable 5 minutes, qui n'ouvre
   que les
   routes MFA. ``request.user`` reste anonyme : aucune route protégée n'est atteignable ;
3. **authentifiée** : ``django.contrib.auth.login`` (nouvelle clé de session), après MFA si elle est exigée.

Aucun mot de passe, code, secret ni jeton n'est journalisé ou renvoyé dans une erreur.

P2.6 (RLS) : avant authentification, chaque accès à la base est limité au compte en cours de vérification
(``identity_scope``) ou à la recherche d'UN e-mail (``app.auth_email``) ; jamais de lecture globale des
comptes.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.http import HttpRequest

from apps.audit.services import record_event
from apps.core.db_scope import db_scope, identity_scope
from apps.organizations.models import Organization
from apps.organizations.tenancy import TenantContext
from apps.users.models import User
from apps.users.rbac import require_permission, requires_mfa

from . import mfa, throttling
from .backends import account_usable
from .tasks import send_password_reset_email
from .tokens import user_for_reset_token

PENDING_KEY = "rbi.auth.pending"
AUTH_AT_KEY = "rbi.auth.at"
MFA_VERIFIED_KEY = "rbi.auth.mfa"
BACKEND = "apps.authentication.backends.RBIAuthBackend"


class LoginStep(StrEnum):
    AUTHENTICATED = "AUTHENTICATED"
    MFA_REQUIRED = "MFA_REQUIRED"
    MFA_ENROLLMENT_REQUIRED = "MFA_ENROLLMENT_REQUIRED"


class AuthError(Exception):
    """Erreur présentable au client : titre et détail génériques, jamais d'information interne."""

    status = 400
    title = "Requête invalide"
    detail: str | None = None

    def __init__(self, *, retry_after: int | None = None, errors: dict[str, list[str]] | None = None) -> None:
        super().__init__(self.title)
        self.retry_after = retry_after
        self.errors = errors


class InvalidCredentials(AuthError):
    status, title = 401, "Identifiants incorrects"


class TooManyAttempts(AuthError):
    status, title = 429, "Trop de tentatives"
    detail = "Veuillez réessayer plus tard."


class OrganizationSuspended(AuthError):
    status, title = 403, "Organisme suspendu"
    detail = "L'accès de votre organisme est temporairement suspendu."


class MfaSessionMissing(AuthError):
    status, title = 401, "Session expirée"
    detail = "Veuillez vous reconnecter."


class InvalidMfaCode(AuthError):
    status, title = 400, "Code invalide ou expiré"


class InvalidResetLink(AuthError):
    status, title = 400, "Lien expiré ou invalide"


class PasswordPolicyError(AuthError):
    status, title = 400, "Mot de passe non conforme"


class ActionNotAllowed(AuthError):
    status, title = 403, "Vous n'avez pas accès à cette ressource"


def _ip(request: HttpRequest) -> str:
    return throttling.client_ip(request)


# --- Connexion -------------------------------------------------------------------------------


def login_with_password(request: HttpRequest, email: str, password: str) -> LoginStep:
    identifier = (email or "").strip().lower()
    ip = _ip(request)
    lock = throttling.login_lock(identifier, ip)
    if lock:
        record_event("auth.login", outcome="denied", actor_id=None, details={"reason": "throttled"})
        raise TooManyAttempts(retry_after=lock.retry_after)

    user = authenticate(request, email=identifier, password=password or "")
    if not isinstance(user, User):
        throttling.register_login_failure(identifier, ip)
        record_event(
            "auth.login", outcome="failure", actor_id=None, details={"reason": "invalid_credentials"}
        )
        raise InvalidCredentials

    if user.organization_id is not None:
        status = user.organization.status if user.organization else None
        if status != Organization.Status.ACTIVE:
            record_event(
                "auth.login",
                outcome="denied",
                actor_id=user.pk,
                organization_id=user.organization_id,
                object_type="user",
                object_id=user.pk,
                details={"reason": "organization_not_active", "status": status},
            )
            # Message spécifique pour une suspension (écran 6), après vérification du mot de passe uniquement.
            if status == Organization.Status.SUSPENDUE:
                raise OrganizationSuspended
            raise InvalidCredentials

    throttling.reset_login_failures(identifier)
    request.session.flush()  # aucune donnée d'une session antérieure ne survit (nouvelle clé)

    if mfa.mfa_needed(user):
        lock = throttling.mfa_lock(str(user.pk))
        if lock:
            raise TooManyAttempts(retry_after=lock.retry_after)
        step = LoginStep.MFA_REQUIRED if mfa.mfa_enabled(user) else LoginStep.MFA_ENROLLMENT_REQUIRED
        request.session[PENDING_KEY] = {
            "user_id": str(user.pk),
            "step": step.value,
            "at": time.time(),
            "stamp": str(user.security_stamp),
        }
        record_event(
            "auth.login",
            outcome="success",
            actor_id=user.pk,
            organization_id=user.organization_id,
            details={"next": step.value},
        )
        return step

    _complete_login(request, user, mfa_verified=False)
    return LoginStep.AUTHENTICATED


def _complete_login(request: HttpRequest, user: User, *, mfa_verified: bool) -> None:
    request.session.pop(PENDING_KEY, None)
    with identity_scope(user.pk):  # login() enregistre last_login sur la ligne du compte
        login(request, user, backend=BACKEND)  # renouvelle la clé de session (fixation de session)
    request.session[AUTH_AT_KEY] = time.time()
    request.session[MFA_VERIFIED_KEY] = mfa_verified
    record_event(
        "auth.session.open",
        outcome="success",
        actor_id=user.pk,
        organization_id=user.organization_id,
        details={"mfa": mfa_verified},
    )


def _pending(request: HttpRequest) -> tuple[User, LoginStep]:
    data: dict[str, Any] | None = request.session.get(PENDING_KEY)
    if not data or time.time() - float(data.get("at", 0)) > settings.RBI_MFA_PENDING_TTL:
        request.session.pop(PENDING_KEY, None)
        raise MfaSessionMissing
    try:
        with identity_scope(data.get("user_id")):  # identifiant conservé côté serveur dans la session
            user = User.objects.select_related("organization").filter(pk=str(data.get("user_id"))).first()
    except (ValueError, ValidationError):  # identifiant illisible : traité comme une session expirée
        user = None
    if user is None or not account_usable(user) or str(user.security_stamp) != data.get("stamp"):
        request.session.pop(PENDING_KEY, None)
        raise MfaSessionMissing
    return user, LoginStep(data["step"])


def start_enrollment(request: HttpRequest) -> dict[str, str]:
    """Enrôlement TOTP pendant la connexion (première connexion d'un rôle à MFA obligatoire)."""
    user, step = _pending(request)
    if step != LoginStep.MFA_ENROLLMENT_REQUIRED:
        raise ActionNotAllowed
    device = mfa.start_totp_enrollment(user)
    record_event(
        "auth.mfa.enroll.start", outcome="success", actor_id=user.pk, organization_id=user.organization_id
    )
    return mfa.provisioning(device)


def verify_mfa(request: HttpRequest, code: str) -> tuple[LoginStep, list[str] | None]:
    user, step = _pending(request)
    lock = throttling.mfa_lock(str(user.pk))
    if lock:
        request.session.pop(PENDING_KEY, None)
        raise TooManyAttempts(retry_after=lock.retry_after)
    code = (code or "").strip()
    backup_codes: list[str] | None = None
    method = "totp"

    if step == LoginStep.MFA_REQUIRED:
        ok = mfa.verify_totp(mfa.confirmed_device(user), code)
        if not ok and not code.isdigit():
            ok = mfa.use_backup_code(user, code)
            method = "backup_code"
    else:
        device = mfa.pending_device(user)
        ok = mfa.verify_totp(device, code)
        if ok and device is not None:
            mfa.confirm_device(device)
            backup_codes = mfa.generate_backup_codes(user)
            record_event(
                "auth.mfa.enroll.confirm",
                outcome="success",
                actor_id=user.pk,
                organization_id=user.organization_id,
            )

    if not ok:
        locked = throttling.register_mfa_failure(str(user.pk))
        record_event(
            "auth.mfa.verify",
            outcome="failure",
            actor_id=user.pk,
            organization_id=user.organization_id,
            details={"locked": locked},
        )
        if locked:
            request.session.pop(PENDING_KEY, None)
            raise TooManyAttempts(retry_after=throttling.MFA_LOCK)
        raise InvalidMfaCode

    throttling.reset_mfa_failures(str(user.pk))
    record_event(
        "auth.mfa.verify",
        outcome="success",
        actor_id=user.pk,
        organization_id=user.organization_id,
        details={"method": method},
    )
    _complete_login(request, user, mfa_verified=True)
    return LoginStep.AUTHENTICATED, backup_codes


def logout_session(request: HttpRequest) -> None:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        record_event(
            "auth.session.close", outcome="success", actor_id=user.pk, organization_id=user.organization_id
        )
    logout(request)  # vide et supprime la session (y compris un état « en attente de MFA »)


# --- Mot de passe ------------------------------------------------------------------------------


def _validate_new_password(password: str, user: User) -> None:
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise PasswordPolicyError(errors={"password": list(exc.messages)}) from exc


def request_password_reset(request: HttpRequest, email: str) -> None:
    """Réponse identique dans tous les cas (écran 8) : seul un compte utilisable reçoit un lien.

    Temps de réponse indépendant de l'existence du compte : mêmes opérations dans tous les cas
    (une recherche, une tâche programmée, un événement d'audit) ; l'envoi SMTP a lieu dans le worker.
    """
    identifier = (email or "").strip().lower()
    allowed = throttling.allow_password_reset(identifier, _ip(request))
    with db_scope(current_user="", current_org="", auth_email=identifier, platform=""):
        user = User.objects.select_related("organization").filter(email=identifier).first()
    target = user if allowed and user is not None and account_usable(user) else None
    send_password_reset_email.delay(str(target.pk) if target else None)
    if target is None:
        record_event("auth.password_reset.request", outcome="denied", actor_id=None)
        return
    user = target
    record_event(
        "auth.password_reset.request", outcome="success", actor_id=None, object_type="user", object_id=user.pk
    )


@transaction.atomic
def confirm_password_reset(token: str, password: str) -> None:
    user = user_for_reset_token(token or "")
    if user is None or not account_usable(user):
        record_event("auth.password_reset.confirm", outcome="denied", actor_id=None)
        raise InvalidResetLink
    _validate_new_password(password or "", user)
    user.set_password(password)
    user.rotate_security_stamp()  # invalide le lien, toutes les sessions et tout état « en attente »
    with identity_scope(user.pk):
        user.save(update_fields=["password", "security_stamp"])
    throttling.reset_login_failures(user.email)
    record_event(
        "auth.password_reset.confirm",
        outcome="success",
        actor_id=user.pk,
        organization_id=user.organization_id,
    )


def _reauthenticate(request: HttpRequest, user: User, password: str) -> None:
    """Confirmation du mot de passe actuel pour une opération sensible ; échecs comptés comme à la
    connexion."""
    lock = throttling.login_lock(user.email, _ip(request))
    if lock:
        raise TooManyAttempts(retry_after=lock.retry_after)
    if not user.check_password(password or ""):
        throttling.register_login_failure(user.email, _ip(request))
        record_event(
            "auth.reauthenticate", outcome="failure", actor_id=user.pk, organization_id=user.organization_id
        )
        raise InvalidCredentials


@transaction.atomic
def change_password(request: HttpRequest, current_password: str, new_password: str) -> None:
    user: User = request.user  # type: ignore[assignment]
    _reauthenticate(request, user, current_password)
    _validate_new_password(new_password or "", user)
    user.set_password(new_password)
    user.rotate_security_stamp()
    user.save(update_fields=["password", "security_stamp"])
    update_session_auth_hash(
        request, user
    )  # la session courante reste valide, toutes les autres sont fermées
    record_event(
        "auth.password.change", outcome="success", actor_id=user.pk, organization_id=user.organization_id
    )


@transaction.atomic
def revoke_other_sessions(request: HttpRequest, password: str) -> None:
    user: User = request.user  # type: ignore[assignment]
    _reauthenticate(request, user, password)
    user.rotate_security_stamp()
    user.save(update_fields=["security_stamp"])
    update_session_auth_hash(request, user)
    record_event(
        "auth.sessions.revoke_others",
        outcome="success",
        actor_id=user.pk,
        organization_id=user.organization_id,
    )


# --- Gestion de la MFA par l'utilisateur authentifié (écran 29) --------------------------------

RENEW_KEY = "rbi.auth.mfa_renewal"


def renew_totp_start(request: HttpRequest, password: str) -> dict[str, str]:
    """Activation volontaire ou renouvellement : l'appareil actuel reste valide jusqu'à confirmation du
    nouveau."""
    user: User = request.user  # type: ignore[assignment]
    _reauthenticate(request, user, password)
    device = mfa.start_totp_enrollment(user)
    request.session[RENEW_KEY] = {"device_id": device.pk, "at": time.time()}
    record_event(
        "auth.mfa.renew.start", outcome="success", actor_id=user.pk, organization_id=user.organization_id
    )
    return mfa.provisioning(device)


@transaction.atomic
def renew_totp_confirm(request: HttpRequest, code: str) -> list[str]:
    user: User = request.user  # type: ignore[assignment]
    data = request.session.get(RENEW_KEY)
    device = mfa.pending_device(user)
    if (
        not data
        or device is None
        or device.pk != data.get("device_id")
        or time.time() - float(data.get("at", 0)) > settings.RBI_MFA_PENDING_TTL
    ):
        raise MfaSessionMissing
    if not mfa.verify_totp(device, (code or "").strip()):
        throttling.register_mfa_failure(str(user.pk))
        raise InvalidMfaCode
    mfa.confirm_device(device)
    codes = mfa.generate_backup_codes(user)
    request.session.pop(RENEW_KEY, None)
    request.session[MFA_VERIFIED_KEY] = True
    user.rotate_security_stamp()
    user.save(update_fields=["security_stamp"])
    update_session_auth_hash(request, user)
    record_event(
        "auth.mfa.renew.confirm", outcome="success", actor_id=user.pk, organization_id=user.organization_id
    )
    return codes


def regenerate_backup_codes(request: HttpRequest, password: str) -> list[str]:
    user: User = request.user  # type: ignore[assignment]
    _reauthenticate(request, user, password)
    if not mfa.mfa_enabled(user):
        raise ActionNotAllowed
    codes = mfa.generate_backup_codes(user)
    record_event(
        "auth.mfa.backup_codes.regenerate",
        outcome="success",
        actor_id=user.pk,
        organization_id=user.organization_id,
    )
    return codes


@transaction.atomic
def disable_mfa(request: HttpRequest, password: str) -> None:
    """Désactivation volontaire, impossible pour un rôle à MFA obligatoire."""
    user: User = request.user  # type: ignore[assignment]
    _reauthenticate(request, user, password)
    if requires_mfa(user):
        record_event(
            "auth.mfa.disable",
            outcome="denied",
            actor_id=user.pk,
            organization_id=user.organization_id,
            details={"reason": "mfa_required"},
        )
        raise ActionNotAllowed
    mfa.remove_mfa(user)
    user.rotate_security_stamp()
    user.save(update_fields=["security_stamp"])
    request.session[MFA_VERIFIED_KEY] = False
    update_session_auth_hash(request, user)
    record_event(
        "auth.mfa.disable", outcome="success", actor_id=user.pk, organization_id=user.organization_id
    )


# --- Récupération par un administrateur (écran 23 « réinitialiser MFA ») -----------------------


def reset_user_mfa(actor: User, context: TenantContext, user_id: uuid.UUID) -> None:
    """L'Administrateur institutionnel réinitialise la MFA d'un utilisateur de SON organisme : facteurs
    supprimés,
    sessions fermées ; l'utilisateur se ré-enrôlera à sa prochaine connexion.

    Les secrets d'un autre compte ne sont jamais lisibles par le rôle applicatif (RLS) : la suppression
    passe par
    la fonction SQL ``rbi_admin_reset_mfa``, qui revérifie organisme, compte et permission ``users.manage``.
    """
    require_permission(actor, "users.manage", context)
    with db_scope(current_user=actor.pk, current_org=context.organization_id, auth_email="", platform=""):
        target = User.objects.get(pk=user_id, organization_id=context.organization_id)
        if target.pk == actor.pk:
            record_event(
                "auth.mfa.admin_reset",
                outcome="denied",
                actor_id=actor.pk,
                organization_id=context.organization_id,
                details={"reason": "self"},
            )
            raise ActionNotAllowed
        with connection.cursor() as cursor:
            cursor.execute("SELECT rbi_admin_reset_mfa(%s)", [target.pk])
    record_event(
        "auth.mfa.admin_reset",
        outcome="success",
        actor_id=actor.pk,
        organization_id=context.organization_id,
        object_type="user",
        object_id=target.pk,
    )


def server_reset_mfa(email: str) -> User:
    """Récupération hors bande (commande serveur ``reset_user_mfa``, rôle de maintenance), notamment pour un
    compte plateforme. Refusée avec le rôle applicatif (P2.6)."""
    from apps.core.maintenance import require_maintenance_role

    require_maintenance_role()
    user = User.objects.get(email=email.strip().lower())
    with transaction.atomic():
        mfa.remove_mfa(user)
        user.rotate_security_stamp()
        user.save(update_fields=["security_stamp"])
    record_event(
        "auth.mfa.server_reset",
        outcome="success",
        actor_id=None,
        system=True,
        object_type="user",
        object_id=user.pk,
        details={"channel": "maintenance"},
    )
    return user
