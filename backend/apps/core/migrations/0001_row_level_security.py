"""P2.6 — Row-Level Security PostgreSQL (ADR 0008).

Exécutée par le rôle propriétaire (service ``migrate``). Les politiques ne visent aucun rôle nommé (PUBLIC) :
elles s'appliquent à tout rôle non propriétaire, donc au rôle applicatif. Le propriétaire (migrations, commandes de
maintenance) n'y est pas soumis : ``FORCE ROW LEVEL SECURITY`` n'est pas utilisé, choix justifié dans l'ADR 0008.

Aucune politique « tout autoriser ». Une table où le RLS est activé sans politique pour une commande refuse
cette commande (refus par défaut de PostgreSQL).
"""

from django.conf import settings
from django.db import migrations

APP = settings.RBI_DB_APP_ROLE

SCOPE_FUNCTIONS = """
CREATE FUNCTION rbi_current_org() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT nullif(current_setting('app.current_org', true), '')::uuid $$;
CREATE FUNCTION rbi_current_user() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT nullif(current_setting('app.current_user', true), '')::uuid $$;
CREATE FUNCTION rbi_auth_email() RETURNS text LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT nullif(current_setting('app.auth_email', true), '') $$;
CREATE FUNCTION rbi_platform() RETURNS text LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT nullif(current_setting('app.platform', true), '') $$;
-- Organisme du compte du périmètre (et de lui seul). SECURITY DEFINER : une politique de users_user ne peut pas
-- interroger users_user sans récursion ; la fonction ne révèle rien d'autre que l'organisme de ce compte.
CREATE FUNCTION rbi_current_user_org() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$ SELECT organization_id FROM users_user WHERE id = rbi_current_user() $$;
REVOKE ALL ON FUNCTION rbi_current_user_org() FROM PUBLIC;
"""
DROP_SCOPE_FUNCTIONS = """
DROP FUNCTION rbi_current_user_org(); DROP FUNCTION rbi_platform(); DROP FUNCTION rbi_auth_email();
DROP FUNCTION rbi_current_user(); DROP FUNCTION rbi_current_org();
"""

POLICIES = """
-- 1. Données d'un organisme ------------------------------------------------------------------------
ALTER TABLE integrations_datasource ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_tenant_isolation ON integrations_datasource FOR ALL
    USING (organization_id = rbi_current_org())
    WITH CHECK (organization_id = rbi_current_org());

-- 2. Organismes et cycle de vie (niveau plateforme) ------------------------------------------------
ALTER TABLE organizations_organization ENABLE ROW LEVEL SECURITY;
-- Visible : son organisme, celui des comptes visibles (sous-requête elle-même filtrée par RLS),
-- ou tous pendant une opération plateforme délivrée.
CREATE POLICY rbi_org_select ON organizations_organization FOR SELECT
    USING (id = rbi_current_org()
           OR rbi_platform() IN ('platform.organizations', 'platform.institutional_admins')
           OR id IN (SELECT u.organization_id FROM users_user u));
CREATE POLICY rbi_org_insert ON organizations_organization FOR INSERT
    WITH CHECK (rbi_platform() = 'platform.organizations');
-- USING inclut institutional_admins pour le verrou de ligne (SELECT … FOR UPDATE) de la désignation
-- du premier administrateur ; seule la gestion des organismes peut réellement modifier la ligne.
CREATE POLICY rbi_org_update ON organizations_organization FOR UPDATE
    USING (rbi_platform() IN ('platform.organizations', 'platform.institutional_admins'))
    WITH CHECK (rbi_platform() = 'platform.organizations');

ALTER TABLE organizations_organizationauthorization ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_authorization_select ON organizations_organizationauthorization FOR SELECT
    USING (rbi_platform() IN ('platform.organizations', 'platform.institutional_admins')
           OR organization_id = rbi_current_org());
CREATE POLICY rbi_authorization_insert ON organizations_organizationauthorization FOR INSERT
    WITH CHECK (rbi_platform() = 'platform.organizations');

ALTER TABLE organizations_accessrequest ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_access_request_select ON organizations_accessrequest FOR SELECT
    USING (rbi_platform() = 'platform.organizations');
-- Formulaire public : seule une demande neuve, non rattachée et non traitée peut être créée sans périmètre.
CREATE POLICY rbi_access_request_insert ON organizations_accessrequest FOR INSERT
    WITH CHECK (rbi_platform() = 'platform.organizations'
                OR (status = 'EN_ATTENTE' AND organization_id IS NULL
                    AND processed_at IS NULL AND processed_by_id IS NULL));
CREATE POLICY rbi_access_request_update ON organizations_accessrequest FOR UPDATE
    USING (rbi_platform() = 'platform.organizations')
    WITH CHECK (rbi_platform() = 'platform.organizations');

-- 3. Identité --------------------------------------------------------------------------------------
ALTER TABLE users_user ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_user_select ON users_user FOR SELECT
    USING (id = rbi_current_user()
           OR (organization_id IS NOT NULL AND organization_id = rbi_current_org())
           OR (rbi_auth_email() IS NOT NULL AND email = rbi_auth_email()));
CREATE POLICY rbi_user_insert ON users_user FOR INSERT
    WITH CHECK (organization_id IS NOT NULL
                AND (organization_id = rbi_current_org()
                     OR rbi_platform() = 'platform.institutional_admins'));
-- Son propre compte (sans pouvoir changer d'organisme) ou un compte de l'organisme du contexte.
CREATE POLICY rbi_user_update ON users_user FOR UPDATE
    USING (id = rbi_current_user()
           OR (organization_id IS NOT NULL AND organization_id = rbi_current_org()))
    WITH CHECK ((id = rbi_current_user() AND organization_id IS NOT DISTINCT FROM rbi_current_user_org())
                OR (organization_id IS NOT NULL AND organization_id = rbi_current_org()));

ALTER TABLE users_user_role ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_user_role_select ON users_user_role FOR SELECT
    USING (user_id = rbi_current_user()
           OR (organization_id IS NOT NULL AND organization_id = rbi_current_org())
           OR (rbi_platform() = 'platform.institutional_admins' AND scope = 'organization'));
CREATE POLICY rbi_user_role_insert ON users_user_role FOR INSERT
    WITH CHECK (scope = 'organization' AND organization_id IS NOT NULL
                AND (organization_id = rbi_current_org()
                     OR rbi_platform() = 'platform.institutional_admins'));
CREATE POLICY rbi_user_role_update ON users_user_role FOR UPDATE
    USING (organization_id IS NOT NULL AND organization_id = rbi_current_org())
    WITH CHECK (organization_id IS NOT NULL AND organization_id = rbi_current_org());
CREATE POLICY rbi_user_role_delete ON users_user_role FOR DELETE
    USING (organization_id IS NOT NULL AND organization_id = rbi_current_org());

-- Catalogue des rôles : rôles par défaut (organisme NULL) ou rôles de son organisme (V1). Lecture seule.
ALTER TABLE users_role ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_role_select ON users_role FOR SELECT
    USING (organization_id IS NULL OR organization_id = rbi_current_org());

-- 4. Secrets MFA : uniquement ceux du compte du périmètre -------------------------------------------
ALTER TABLE otp_totp_totpdevice ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_own_mfa_device ON otp_totp_totpdevice FOR ALL
    USING (user_id = rbi_current_user()) WITH CHECK (user_id = rbi_current_user());
ALTER TABLE authentication_mfa_backup_code ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_own_backup_code ON authentication_mfa_backup_code FOR ALL
    USING (user_id = rbi_current_user()) WITH CHECK (user_id = rbi_current_user());
"""

UNPROTECT = """
DROP POLICY rbi_own_backup_code ON authentication_mfa_backup_code;
ALTER TABLE authentication_mfa_backup_code DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_own_mfa_device ON otp_totp_totpdevice;
ALTER TABLE otp_totp_totpdevice DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_role_select ON users_role;
ALTER TABLE users_role DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_user_role_delete ON users_user_role;
DROP POLICY rbi_user_role_update ON users_user_role;
DROP POLICY rbi_user_role_insert ON users_user_role;
DROP POLICY rbi_user_role_select ON users_user_role;
ALTER TABLE users_user_role DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_user_update ON users_user;
DROP POLICY rbi_user_insert ON users_user;
DROP POLICY rbi_user_select ON users_user;
ALTER TABLE users_user DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_access_request_update ON organizations_accessrequest;
DROP POLICY rbi_access_request_insert ON organizations_accessrequest;
DROP POLICY rbi_access_request_select ON organizations_accessrequest;
ALTER TABLE organizations_accessrequest DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_authorization_insert ON organizations_organizationauthorization;
DROP POLICY rbi_authorization_select ON organizations_organizationauthorization;
ALTER TABLE organizations_organizationauthorization DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_org_update ON organizations_organization;
DROP POLICY rbi_org_insert ON organizations_organization;
DROP POLICY rbi_org_select ON organizations_organization;
ALTER TABLE organizations_organization DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_tenant_isolation ON integrations_datasource;
ALTER TABLE integrations_datasource DISABLE ROW LEVEL SECURITY;
"""

# Moindre privilège : le rôle applicatif ne modifie ni les catalogues globaux ni l'historique des migrations,
# et ne supprime jamais un compte, un organisme, une autorisation ni une demande (fin de vie = statut).
READ_ONLY_TABLES = (
    "auth_group",
    "auth_group_permissions",
    "auth_permission",
    "django_content_type",
    "django_migrations",
    "users_permission",
    "users_role",
    "users_role_permission",
)
NO_DELETE_TABLES = ("users_user", "organizations_organization", "organizations_accessrequest")
NO_UPDATE_DELETE_TABLES = ("organizations_organizationauthorization",)

PRIVILEGES = "\n".join(
    [f'REVOKE INSERT, UPDATE, DELETE ON {t} FROM "{APP}";' for t in READ_ONLY_TABLES]
    + [f'REVOKE DELETE ON {t} FROM "{APP}";' for t in NO_DELETE_TABLES]
    + [f'REVOKE UPDATE, DELETE ON {t} FROM "{APP}";' for t in NO_UPDATE_DELETE_TABLES]
)
RESTORE_PRIVILEGES = "\n".join(
    [f'GRANT INSERT, UPDATE, DELETE ON {t} TO "{APP}";' for t in READ_ONLY_TABLES]
    + [f'GRANT DELETE ON {t} TO "{APP}";' for t in NO_DELETE_TABLES]
    + [f'GRANT UPDATE, DELETE ON {t} TO "{APP}";' for t in NO_UPDATE_DELETE_TABLES]
)

# Fonctions SECURITY DEFINER : exécutées avec les droits du propriétaire, donc hors RLS. Chacune vérifie
# elle-même son périmètre et ne renvoie que le strict nécessaire. search_path figé (pas de détournement).
DEFINER_FUNCTIONS = f"""
CREATE FUNCTION rbi_org_has_active_admin(target uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF rbi_platform() IS DISTINCT FROM 'platform.organizations' THEN
        RAISE EXCEPTION 'rbi: périmètre plateforme requis' USING ERRCODE = '42501';
    END IF;
    RETURN EXISTS (
        SELECT 1 FROM users_user_role ur
        JOIN users_role r ON r.id = ur.role_id
        JOIN users_user u ON u.id = ur.user_id
        WHERE ur.organization_id = target AND r.code = 'ORG_ADMIN' AND r.scope = 'organization'
          AND u.is_active);
END $$;

-- Réinitialisation MFA par un Administrateur institutionnel : supprime les facteurs d'UN compte de son
-- organisme sans jamais rendre lisibles les secrets d'autrui au rôle applicatif.
CREATE FUNCTION rbi_admin_reset_mfa(target uuid) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    actor uuid := rbi_current_user();
    org uuid := rbi_current_org();
BEGIN
    IF actor IS NULL OR org IS NULL OR actor = target THEN
        RAISE EXCEPTION 'rbi: réinitialisation MFA refusée' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users_user WHERE id = target AND organization_id = org) THEN
        RAISE EXCEPTION 'rbi: compte introuvable' USING ERRCODE = 'P0002';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM users_user a
        JOIN users_user_role ur ON ur.user_id = a.id AND ur.organization_id = org
        JOIN users_role_permission rp ON rp.role_id = ur.role_id
        JOIN users_permission p ON p.id = rp.permission_id
        WHERE a.id = actor AND a.organization_id = org AND a.is_active AND p.code = 'users.manage'
    ) THEN
        RAISE EXCEPTION 'rbi: réinitialisation MFA refusée' USING ERRCODE = '42501';
    END IF;
    DELETE FROM otp_totp_totpdevice WHERE user_id = target;
    DELETE FROM authentication_mfa_backup_code WHERE user_id = target;
    UPDATE users_user SET security_stamp = gen_random_uuid() WHERE id = target;
END $$;

GRANT EXECUTE ON FUNCTION rbi_current_user_org() TO "{APP}";
REVOKE ALL ON FUNCTION rbi_org_has_active_admin(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION rbi_admin_reset_mfa(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rbi_org_has_active_admin(uuid) TO "{APP}";
GRANT EXECUTE ON FUNCTION rbi_admin_reset_mfa(uuid) TO "{APP}";
"""
DROP_DEFINER_FUNCTIONS = "DROP FUNCTION rbi_admin_reset_mfa(uuid); DROP FUNCTION rbi_org_has_active_admin(uuid);"


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_user_security_stamp"),
        ("organizations", "0002_rbac"),
        ("integrations", "0001_initial"),
        ("authentication", "0001_initial"),
        ("otp_totp", "0003_add_timestamps"),
    ]

    operations = [
        migrations.RunSQL(SCOPE_FUNCTIONS, DROP_SCOPE_FUNCTIONS),
        migrations.RunSQL(POLICIES, UNPROTECT),
        migrations.RunSQL(PRIVILEGES, RESTORE_PRIVILEGES),
        migrations.RunSQL(DEFINER_FUNCTIONS, DROP_DEFINER_FUNCTIONS),
    ]
