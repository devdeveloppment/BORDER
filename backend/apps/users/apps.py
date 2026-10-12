from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsersConfig(AppConfig):
    name = "apps.users"
    label = "users"
    verbose_name = "Utilisateurs"

    def ready(self) -> None:
        from .catalog import validate_catalog
        from .rbac_sync import on_post_migrate

        validate_catalog()
        post_migrate.connect(on_post_migrate, sender=self, dispatch_uid="rbi_sync_rbac_catalog")
