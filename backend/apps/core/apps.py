from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Socle"

    def ready(self) -> None:
        # Proxy de confiance validé au démarrage : une configuration douteuse empêche de servir (P2.10).
        from .client_ip import trusted_networks

        trusted_networks()
