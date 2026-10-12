"""Remédiation du défaut découvert en P2.11 : ``search_path`` des fonctions ``SECURITY DEFINER``.

Ces huit fonctions fixaient ``search_path = pg_catalog, public`` et nomment leurs tables (et la séquence du journal)
sans schéma. PostgreSQL parcourt alors d'abord le schéma temporaire de la session pour résoudre une table ou une
séquence ; le rôle applicatif peut créer des tables temporaires : une table temporaire homonyme aurait été lue par
la fonction, avec les droits du propriétaire. Placer ``pg_temp`` explicitement EN DERNIER l'empêche
(documentation PostgreSQL, « Writing SECURITY DEFINER Functions Safely »). Les fonctions ne sont jamais résolues
dans ``pg_temp`` et le rôle applicatif ne peut rien créer dans ``public``.

Aucun corps, signature, propriétaire, privilège ni politique n'est modifié. Réversible : la migration inverse
rétablit exactement la configuration antérieure.
"""

from django.db import migrations

# Signatures exactes (catalogue de la base de développement, 12/10/2026) ; sept exécutables par le rôle applicatif,
# la huitième (rbi_audit_seal) exécutée par le déclencheur d'insertion du journal d'audit.
FUNCTIONS = (
    "public.rbi_admin_reset_mfa(uuid)",
    "public.rbi_audit_org_reader()",
    "public.rbi_audit_platform_reader()",
    "public.rbi_audit_seal()",
    "public.rbi_current_user_org()",
    "public.rbi_org_has_active_admin(uuid)",
    "public.rbi_org_mfa_enabled_users()",
    "public.rbi_platform_org_user_counts()",
)
SAFE = "pg_catalog, public, pg_temp"
PREVIOUS = "pg_catalog, public"

FORWARD = "".join(f"ALTER FUNCTION {name} SET search_path = {SAFE};\n" for name in FUNCTIONS)
REVERSE = "".join(f"ALTER FUNCTION {name} SET search_path = {PREVIOUS};\n" for name in FUNCTIONS)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_api_read_functions"),
        ("audit", "0001_initial"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
