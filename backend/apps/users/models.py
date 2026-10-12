"""Utilisateurs, rôles et permissions (spécification interne non publiée §7, §9.12, §14.3).

``User`` n'utilise PAS ``PermissionsMixin`` : RBI a un seul système d'autorisation, le RBAC ci-dessous.
Les permissions de Django (``is_superuser``, groupes, permissions par utilisateur) sont retirées en P2.4 :
``is_superuser`` court-circuitait toute vérification, ce qui est contraire au moindre privilège.

Séparation des portées garantie par PostgreSQL (clés étrangères composites, migration 0004) :
- un rôle ne contient que des permissions de SA portée (plateforme OU organisme) ;
- une affectation reprend la portée du rôle et l'organisme de l'utilisateur.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from apps.core.models import TimestampedModel

from .managers import UserManager


class Scope(models.TextChoices):
    PLATFORM = "platform", "Plateforme"
    ORGANIZATION = "organization", "Organisme"


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("adresse e-mail", unique=True)
    first_name = models.CharField("prénom", max_length=150, blank=True)
    last_name = models.CharField("nom", max_length=150, blank=True)
    is_active = models.BooleanField("actif", default=True)
    date_joined = models.DateTimeField("date de création", default=timezone.now)
    # Renouvelé à chaque événement de sécurité (mot de passe, MFA, désactivation, révocation des sessions) :
    # il entre dans l'empreinte de session et dans les jetons de réinitialisation, qui deviennent tous
    # invalides.
    security_stamp = models.UUIDField("empreinte de sécurité", default=uuid.uuid4, editable=False)
    # Un utilisateur organisationnel appartient à un et un seul organisme (§7.1).
    # NULL = compte plateforme : aucun accès aux données opérationnelles (voir apps.organizations.tenancy).
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
        verbose_name="organisme",
    )

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        constraints = (
            # Cible de la clé étrangère composite des affectations (user_id, organization_id).
            models.UniqueConstraint(fields=("id", "organization"), name="user_id_organization_unique"),
        )

    @property
    def is_platform_account(self) -> bool:
        return self.organization_id is None

    def rotate_security_stamp(self) -> None:
        """Invalide toutes les sessions et tous les jetons émis jusqu'ici (à enregistrer par l'appelant)."""
        self.security_stamp = uuid.uuid4()

    def get_session_auth_hash(self) -> str:
        """Empreinte vérifiée par Django à chaque requête : mot de passe ET empreinte de sécurité."""
        return salted_hmac(
            "rbi.users.User.get_session_auth_hash",
            f"{self.password}:{self.security_stamp}",
            algorithm="sha256",
        ).hexdigest()

    def __str__(self) -> str:
        return self.email


class Permission(models.Model):
    """Droit atomique (ex. ``alerts.decide``), synchronisé depuis apps.users.catalog."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField("code", max_length=100, unique=True)
    module = models.CharField("module", max_length=50)
    scope = models.CharField("portée", max_length=20, choices=Scope.choices)
    description = models.TextField("description")

    class Meta:
        db_table = "users_permission"
        verbose_name = "permission"
        verbose_name_plural = "permissions"
        ordering = ("code",)
        constraints = (
            models.CheckConstraint(condition=Q(scope__in=Scope.values), name="permission_scope_valid"),
            models.CheckConstraint(
                condition=Q(code__regex=r"^[a-z_]+\.[a-z_]+$"), name="permission_code_format"
            ),
            models.UniqueConstraint(fields=("id", "scope"), name="permission_id_scope_unique"),
        )

    def __str__(self) -> str:
        return self.code


class Role(TimestampedModel):
    """Ensemble nommé de permissions, exercé à une portée.

    Rôles par défaut (``is_system``) : ``organization`` NULL, définis par le catalogue,
    non modifiables en base.
    Rôles personnalisés par organisme : V1 (§14.3), non créés en MVP.
    """

    code = models.CharField("code", max_length=50)
    name = models.CharField("libellé", max_length=100)
    scope = models.CharField("portée", max_length=20, choices=Scope.choices)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    is_system = models.BooleanField("rôle par défaut", default=False)
    mfa_required = models.BooleanField("MFA obligatoire", default=True)
    permissions: models.ManyToManyField[Permission, RolePermission] = models.ManyToManyField(
        Permission, through="RolePermission", related_name="roles"
    )

    class Meta:
        verbose_name = "rôle"
        verbose_name_plural = "rôles"
        ordering = ("scope", "code")
        constraints = (
            models.CheckConstraint(condition=Q(scope__in=Scope.values), name="role_scope_valid"),
            models.CheckConstraint(condition=Q(code__regex=r"^[A-Z_]+$"), name="role_code_format"),
            # Un rôle plateforme n'appartient à aucun organisme ; un rôle par défaut non plus.
            models.CheckConstraint(
                condition=~Q(scope="platform") | Q(organization__isnull=True),
                name="role_platform_no_organization",
            ),
            models.CheckConstraint(
                condition=~Q(is_system=True) | Q(organization__isnull=True),
                name="role_system_no_organization",
            ),
            models.UniqueConstraint(
                fields=("code", "scope"),
                condition=Q(organization__isnull=True),
                name="role_code_unique_per_scope",
            ),
            models.UniqueConstraint(
                fields=("organization", "code"),
                condition=Q(organization__isnull=False),
                name="role_code_unique_per_organization",
            ),
            models.UniqueConstraint(fields=("id", "scope"), name="role_id_scope_unique"),
        )

    def __str__(self) -> str:
        return f"{self.code} ({self.scope})"


class RolePermission(models.Model):
    """Composition d'un rôle.

    ``role_scope`` et ``permission_scope`` sont vérifiés par clés composites (migration 0004) et doivent être
    égaux : un rôle d'organisme ne peut pas contenir une permission plateforme.
    """

    id = models.BigAutoField(primary_key=True)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="+")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="+")
    role_scope = models.CharField(max_length=20, choices=Scope.choices)
    permission_scope = models.CharField(max_length=20, choices=Scope.choices)

    class Meta:
        db_table = "users_role_permission"
        constraints = (
            models.UniqueConstraint(fields=("role", "permission"), name="role_permission_unique"),
            models.CheckConstraint(
                condition=Q(role_scope=models.F("permission_scope")), name="role_permission_same_scope"
            ),
        )

    def __str__(self) -> str:
        return f"{self.role_id} -> {self.permission_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.role_scope = self.role.scope
        self.permission_scope = self.permission.scope
        super().save(*args, **kwargs)


class UserRole(models.Model):
    """Affectation d'un rôle à un utilisateur.

    ``scope`` reprend celle du rôle et ``organization`` celle de l'utilisateur
    (clés composites, migration 0004) : une affectation d'organisme est liée à l'organisme réel
    de l'utilisateur, jamais à une valeur fournie par un client. Les affectations passent par
    apps.users.services (règles contre l'élévation de privilèges).
    """

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="+")
    scope = models.CharField(max_length=20, choices=Scope.choices)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users_user_role"
        constraints = (
            models.UniqueConstraint(fields=("user", "role"), name="user_role_unique"),
            models.CheckConstraint(
                condition=(Q(scope="platform") & Q(organization__isnull=True))
                | (Q(scope="organization") & Q(organization__isnull=False)),
                name="user_role_scope_organization_consistent",
            ),
        )
        indexes = (models.Index(fields=("organization", "role"), name="user_role_org_role_idx"),)

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.role_id}"
