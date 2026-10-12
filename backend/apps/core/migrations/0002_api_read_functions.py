"""P2.8 — Deux lectures bornées pour l'API (ADR 0010), sans ouvrir les tables protégées au rôle applicatif.

- ``rbi_org_mfa_enabled_users()`` : identifiants des comptes de l'organisme du contexte qui ont un TOTP confirmé
  (écran 23, colonne « MFA »). Les appareils et leurs secrets restent illisibles (RLS P2.6 : titulaire seul) ;
  seul le booléen est révélé, et seulement à un compte actif de l'organisme ayant ``users.view``.
- ``rbi_platform_org_user_counts()`` : nombre de comptes par organisme (écran 31, statistique agrégée sans
  contenu, §7.2 A), pendant une opération ``platform.organizations`` d'un compte plateforme qui détient
  cette permission.

SECURITY DEFINER, ``search_path`` figé, exécution réservée au rôle applicatif ; refus explicite (42501) hors
périmètre, jamais un résultat vide trompeur.
"""

from django.conf import settings
from django.db import migrations

APP = settings.RBI_DB_APP_ROLE

FUNCTIONS = f"""
CREATE FUNCTION rbi_org_mfa_enabled_users() RETURNS SETOF uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF rbi_current_org() IS NULL OR NOT EXISTS (
        SELECT 1 FROM users_user a
        JOIN users_user_role ur ON ur.user_id = a.id AND ur.scope = 'organization'
                                AND ur.organization_id = a.organization_id
        JOIN users_role r ON r.id = ur.role_id AND r.scope = 'organization'
        JOIN users_role_permission rp ON rp.role_id = r.id
        JOIN users_permission p ON p.id = rp.permission_id AND p.scope = 'organization'
        WHERE a.id = rbi_current_user() AND a.organization_id = rbi_current_org() AND a.is_active
          AND p.code = 'users.view'
    ) THEN
        RAISE EXCEPTION 'rbi: lecture du statut MFA refusée' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
        SELECT DISTINCT d.user_id FROM otp_totp_totpdevice d
        JOIN users_user u ON u.id = d.user_id
        WHERE d.confirmed AND u.organization_id = rbi_current_org();
END $$;

CREATE FUNCTION rbi_platform_org_user_counts() RETURNS TABLE (organization_id uuid, users_count bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF rbi_platform() IS DISTINCT FROM 'platform.organizations' OR NOT EXISTS (
        SELECT 1 FROM users_user a
        JOIN users_user_role ur ON ur.user_id = a.id AND ur.scope = 'platform' AND ur.organization_id IS NULL
        JOIN users_role r ON r.id = ur.role_id AND r.scope = 'platform'
        JOIN users_role_permission rp ON rp.role_id = r.id
        JOIN users_permission p ON p.id = rp.permission_id AND p.scope = 'platform'
        WHERE a.id = rbi_current_user() AND a.organization_id IS NULL AND a.is_active
          AND p.code = 'platform.organizations'
    ) THEN
        RAISE EXCEPTION 'rbi: statistique plateforme refusée' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
        SELECT u.organization_id, count(*) FROM users_user u
        WHERE u.organization_id IS NOT NULL GROUP BY u.organization_id;
END $$;

REVOKE ALL ON FUNCTION rbi_org_mfa_enabled_users() FROM PUBLIC;
REVOKE ALL ON FUNCTION rbi_platform_org_user_counts() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rbi_org_mfa_enabled_users() TO "{APP}";
GRANT EXECUTE ON FUNCTION rbi_platform_org_user_counts() TO "{APP}";
"""
DROP_FUNCTIONS = "DROP FUNCTION rbi_platform_org_user_counts(); DROP FUNCTION rbi_org_mfa_enabled_users();"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_row_level_security"),
    ]

    operations = [migrations.RunSQL(FUNCTIONS, DROP_FUNCTIONS)]
