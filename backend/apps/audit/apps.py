from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "apps.audit"
    label = "audit"
    verbose_name = "Journal d'audit"

    def ready(self) -> None:
        from django.core.signals import request_finished

        from . import checks  # noqa: F401  (enregistrement du contrôle système)
        from .writer import close_connection

        # Connexion d'écriture fermée en fin de requête : aucune connexion laissée au ramasse-miettes
        # lorsque le serveur crée un thread par requête. Les événements sont rares (connexions,
        # administration) : le coût d'une connexion par requête qui en écrit reste négligeable.
        request_finished.connect(lambda **_: close_connection(), weak=False, dispatch_uid="rbi_audit_writer")
