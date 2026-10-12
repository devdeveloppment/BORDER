"""P2.7 — Journal d'audit append-only et chaîné (ADR 0009).

Exécutée par le rôle propriétaire (service ``migrate``). Protections, de la plus forte à la plus faible :

1. **Privilèges** (rôle applicatif) : INSERT limité aux colonnes descriptives, SELECT filtré par le RLS ; ni
   UPDATE, ni DELETE, ni TRUNCATE, ni accès à la séquence ni à la table des têtes de chaîne en écriture.
2. **RLS** : une entrée ne peut être attribuée qu'à l'organisme du contexte serveur, à celui du compte du
   périmètre, ou (opération plateforme délivrée) à un organisme géré ; la lecture exige la permission
   ``audit.view`` dans son organisme ou ``platform.audit`` pour la plateforme, revérifiée en SQL.
3. **Scellement** (déclencheur SECURITY DEFINER) : identifiant, horodatage UTC et empreintes calculés par
   PostgreSQL ; chaînage SHA-256 par organisme et pour la plateforme, sous verrou de la tête de chaîne.
4. **Immuabilité** (déclencheurs) : UPDATE, DELETE et TRUNCATE refusés, y compris pour le propriétaire tant
   qu'il ne désactive pas les déclencheurs. Ce n'est PAS une protection contre un propriétaire ou un
   superutilisateur malveillant : c'est le rôle du chaînage (détection) et d'un ancrage externe (ADR 0009).
"""

from django.conf import settings
from django.db import migrations, models

APP = settings.RBI_DB_APP_ROLE

INSERTABLE_COLUMNS = (
    "scope",
    "organization_id",
    "actor_type",
    "actor_id",
    "action",
    "outcome",
    "object_type",
    "object_id",
    "old_value",
    "new_value",
    "metadata",
    "ip_address",
    "request_id",
)

# Clés interdites dans les données JSON, à toute profondeur (défense en profondeur ; la validation applicative
# refuse les mêmes clés avant l'écriture). Voir apps.audit.services.FORBIDDEN_KEY.
FORBIDDEN_KEY_REGEX = (
    "password|passwd|secret|token|otp|cookie|session|csrf|backup_code|api_key|apikey|private_key|credential"
)

FUNCTIONS = f"""
CREATE FUNCTION rbi_audit_json_safe(value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT value IS NULL OR NOT jsonb_path_exists(
        value,
        'strict $.** ? (@.type() == "object").keyvalue() ? (@.key like_regex "{FORBIDDEN_KEY_REGEX}" flag "i")')
$$;

-- Champ d'un message canonique : « longueur:valeur; » (longueur en caractères), « ~; » pour NULL. Sans
-- ambiguïté quel que soit le contenu. Reproduit à l'identique par apps.audit.integrity (vérificateur Python).
CREATE FUNCTION rbi_audit_netstring(value text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN value IS NULL THEN '~;' ELSE length(value)::text || ':' || value || ';' END
$$;

CREATE FUNCTION rbi_audit_digest(previous text, fields text[]) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT encode(sha256(convert_to(
        rbi_audit_netstring('rbi-audit-v1') || rbi_audit_netstring(previous)
        || coalesce((SELECT string_agg(rbi_audit_netstring(f), '' ORDER BY i)
                     FROM unnest(fields) WITH ORDINALITY AS t(f, i)), ''),
        'UTF8')), 'hex')
$$;
"""
DROP_FUNCTIONS = """
DROP FUNCTION rbi_audit_digest(text, text[]); DROP FUNCTION rbi_audit_netstring(text);
DROP FUNCTION rbi_audit_json_safe(jsonb);
"""

TABLES = r"""
CREATE SEQUENCE audit_auditlog_id_seq AS bigint;

CREATE TABLE audit_auditlog (
    -- Attribués par le déclencheur de scellement, jamais par l'appelant (aucun privilège sur ces colonnes).
    id bigint PRIMARY KEY,
    created_at timestamptz NOT NULL,
    prev_hash char(64) NOT NULL CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
    hash char(64) NOT NULL UNIQUE CHECK (hash ~ '^[0-9a-f]{64}$'),
    -- Fournis par apps.audit.services.record_event (contexte serveur).
    scope varchar(20) NOT NULL CHECK (scope IN ('platform', 'organization')),
    organization_id uuid,
    actor_type varchar(20) NOT NULL CHECK (actor_type IN ('user', 'anonymous', 'system')),
    actor_id uuid,
    action varchar(64) NOT NULL CHECK (action ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
    outcome varchar(10) NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
    object_type varchar(40) CHECK (object_type ~ '^[a-z][a-z0-9_]*$'),
    object_id varchar(64) CHECK (object_id ~ '^[A-Za-z0-9_.:-]+$'),
    old_value jsonb CHECK (rbi_audit_json_safe(old_value) AND pg_column_size(old_value) <= 8192),
    new_value jsonb CHECK (rbi_audit_json_safe(new_value) AND pg_column_size(new_value) <= 8192),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object' AND rbi_audit_json_safe(metadata)
               AND pg_column_size(metadata) <= 4096),
    ip_address inet,
    request_id uuid,
    CONSTRAINT audit_actor_identified CHECK ((actor_type = 'user') = (actor_id IS NOT NULL)),
    CONSTRAINT audit_organization_scope CHECK (scope = 'platform' OR organization_id IS NOT NULL),
    CONSTRAINT audit_object_typed CHECK (object_id IS NULL OR object_type IS NOT NULL)
);
ALTER SEQUENCE audit_auditlog_id_seq OWNED BY audit_auditlog.id;
CREATE INDEX audit_auditlog_org_idx ON audit_auditlog (organization_id, id);
CREATE INDEX audit_auditlog_scope_idx ON audit_auditlog (scope, id);
CREATE INDEX audit_auditlog_actor_idx ON audit_auditlog (actor_id, id);

-- Tête de chaque chaîne : clé = identifiant de l'organisme, ou 'platform'.
CREATE TABLE audit_chain (
    chain_key varchar(64) PRIMARY KEY,
    last_id bigint,
    last_hash char(64) NOT NULL,
    length bigint NOT NULL DEFAULT 0,
    updated_at timestamptz
);
"""
DROP_TABLES = "DROP TABLE audit_chain; DROP TABLE audit_auditlog;"

# Scellement : verrou de la tête de chaîne → identifiant → horodatage → empreinte → nouvelle tête. Le verrou est
# tenu jusqu'à la fin de la transaction d'écriture : l'ordre des identifiants d'une chaîne est l'ordre du
# chaînage, et une écriture annulée n'avance pas la tête.
SEAL = """
CREATE FUNCTION rbi_audit_seal() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    chain varchar(64) := CASE WHEN NEW.scope = 'organization' THEN NEW.organization_id::text ELSE 'platform' END;
    previous char(64);
BEGIN
    -- Le déclencheur précède les contraintes CHECK : refus explicite plutôt qu'une clé de chaîne nulle.
    IF chain IS NULL THEN
        RAISE EXCEPTION 'new row for relation "audit_auditlog" violates check constraint "audit_organization_scope"'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO audit_chain (chain_key, last_id, last_hash, length)
        VALUES (chain, NULL, repeat('0', 64), 0) ON CONFLICT (chain_key) DO NOTHING;
    SELECT last_hash INTO previous FROM audit_chain WHERE chain_key = chain FOR UPDATE;
    NEW.id := nextval('audit_auditlog_id_seq');
    NEW.created_at := clock_timestamp();
    NEW.prev_hash := previous;
    NEW.hash := rbi_audit_digest(previous, ARRAY[
        NEW.id::text,
        to_char(NEW.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
        NEW.scope, NEW.organization_id::text, NEW.actor_type, NEW.actor_id::text,
        NEW.action, NEW.outcome, NEW.object_type, NEW.object_id,
        NEW.old_value::text, NEW.new_value::text, NEW.metadata::text,
        NEW.ip_address::text, NEW.request_id::text]);
    UPDATE audit_chain SET last_id = NEW.id, last_hash = NEW.hash, length = length + 1,
                           updated_at = NEW.created_at
        WHERE chain_key = chain;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION rbi_audit_seal() FROM PUBLIC;
CREATE TRIGGER rbi_audit_seal BEFORE INSERT ON audit_auditlog FOR EACH ROW EXECUTE FUNCTION rbi_audit_seal();

-- Immuabilité. Seule exception : la mise à jour de la tête de chaîne par le déclencheur de scellement
-- (profondeur de déclencheur > 1). Un propriétaire peut désactiver ces déclencheurs : voir ADR 0009, limites.
CREATE FUNCTION rbi_audit_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_TABLE_NAME = 'audit_chain' AND TG_OP = 'UPDATE' AND pg_trigger_depth() > 1 THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'rbi: journal d''audit en insertion seule (% refusé sur %)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = '42501';
END $$;
CREATE TRIGGER rbi_audit_immutable BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION rbi_audit_immutable();
CREATE TRIGGER rbi_audit_no_truncate BEFORE TRUNCATE ON audit_auditlog
    FOR EACH STATEMENT EXECUTE FUNCTION rbi_audit_immutable();
CREATE TRIGGER rbi_audit_immutable BEFORE UPDATE OR DELETE ON audit_chain
    FOR EACH ROW EXECUTE FUNCTION rbi_audit_immutable();
CREATE TRIGGER rbi_audit_no_truncate BEFORE TRUNCATE ON audit_chain
    FOR EACH STATEMENT EXECUTE FUNCTION rbi_audit_immutable();
"""
DROP_SEAL = """
DROP TRIGGER rbi_audit_no_truncate ON audit_chain; DROP TRIGGER rbi_audit_immutable ON audit_chain;
DROP TRIGGER rbi_audit_no_truncate ON audit_auditlog; DROP TRIGGER rbi_audit_immutable ON audit_auditlog;
DROP FUNCTION rbi_audit_immutable();
DROP TRIGGER rbi_audit_seal ON audit_auditlog; DROP FUNCTION rbi_audit_seal();
"""

# Lecteurs : la permission RBAC est revérifiée en SQL (pas seulement par le code). SECURITY DEFINER : lecture
# des affectations sans exposer ces tables ; ne renvoie qu'un booléen pour le compte du périmètre.
READERS = f"""
CREATE FUNCTION rbi_audit_org_reader() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT rbi_current_org() IS NOT NULL AND EXISTS (
        SELECT 1 FROM users_user a
        JOIN users_user_role ur ON ur.user_id = a.id AND ur.scope = 'organization'
                                AND ur.organization_id = a.organization_id
        JOIN users_role r ON r.id = ur.role_id AND r.scope = 'organization'
        JOIN users_role_permission rp ON rp.role_id = r.id
        JOIN users_permission p ON p.id = rp.permission_id AND p.scope = 'organization'
        WHERE a.id = rbi_current_user() AND a.organization_id = rbi_current_org() AND a.is_active
          AND p.code = 'audit.view')
$$;
CREATE FUNCTION rbi_audit_platform_reader() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT rbi_platform() IS NOT DISTINCT FROM 'platform.audit' AND EXISTS (
        SELECT 1 FROM users_user a
        JOIN users_user_role ur ON ur.user_id = a.id AND ur.scope = 'platform' AND ur.organization_id IS NULL
        JOIN users_role r ON r.id = ur.role_id AND r.scope = 'platform'
        JOIN users_role_permission rp ON rp.role_id = r.id
        JOIN users_permission p ON p.id = rp.permission_id AND p.scope = 'platform'
        WHERE a.id = rbi_current_user() AND a.organization_id IS NULL AND a.is_active
          AND p.code = 'platform.audit')
$$;
REVOKE ALL ON FUNCTION rbi_audit_org_reader() FROM PUBLIC;
REVOKE ALL ON FUNCTION rbi_audit_platform_reader() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rbi_audit_org_reader() TO "{APP}";
GRANT EXECUTE ON FUNCTION rbi_audit_platform_reader() TO "{APP}";
"""
DROP_READERS = "DROP FUNCTION rbi_audit_platform_reader(); DROP FUNCTION rbi_audit_org_reader();"

POLICIES = """
ALTER TABLE audit_auditlog ENABLE ROW LEVEL SECURITY;
-- Lecture : son organisme avec audit.view (y compris les opérations plateforme le concernant), ou les
-- entrées de portée plateforme avec platform.audit. (SELECT …) : évalué une fois par requête.
CREATE POLICY rbi_audit_select ON audit_auditlog FOR SELECT
    USING ((organization_id = rbi_current_org() AND (SELECT rbi_audit_org_reader()))
           OR (scope = 'platform' AND (SELECT rbi_audit_platform_reader())));
-- Écriture : l'acteur est le compte du périmètre ; l'organisme est celui du contexte, celui du compte du
-- périmètre, ou un organisme géré pendant une opération plateforme délivrée.
CREATE POLICY rbi_audit_insert ON audit_auditlog FOR INSERT
    WITH CHECK ((actor_id IS NULL OR actor_id = rbi_current_user())
                AND (organization_id IS NULL
                     OR organization_id = rbi_current_org()
                     OR organization_id = rbi_current_user_org()
                     OR (scope = 'platform'
                         AND rbi_platform() IN ('platform.organizations', 'platform.institutional_admins'))));

ALTER TABLE audit_chain ENABLE ROW LEVEL SECURITY;
CREATE POLICY rbi_audit_chain_select ON audit_chain FOR SELECT
    USING ((chain_key = rbi_current_org()::text AND (SELECT rbi_audit_org_reader()))
           OR (chain_key = 'platform' AND (SELECT rbi_audit_platform_reader())));
"""
DROP_POLICIES = """
DROP POLICY rbi_audit_chain_select ON audit_chain; ALTER TABLE audit_chain DISABLE ROW LEVEL SECURITY;
DROP POLICY rbi_audit_insert ON audit_auditlog; DROP POLICY rbi_audit_select ON audit_auditlog;
ALTER TABLE audit_auditlog DISABLE ROW LEVEL SECURITY;
"""

# Les privilèges par défaut du cluster (P2.1) accordent SELECT/INSERT/UPDATE/DELETE sur toute nouvelle table
# et l'usage des séquences : tout est retiré puis seul le strict nécessaire est accordé.
PRIVILEGES = f"""
REVOKE ALL ON audit_auditlog, audit_chain FROM PUBLIC, "{APP}";
REVOKE ALL ON SEQUENCE audit_auditlog_id_seq FROM PUBLIC, "{APP}";
GRANT SELECT ON audit_auditlog, audit_chain TO "{APP}";
GRANT INSERT ({", ".join(INSERTABLE_COLUMNS)}) ON audit_auditlog TO "{APP}";
"""

# Retour arrière : détruit le journal. Refusé tant qu'il contient des entrées, sauf décision explicite du
# propriétaire dans sa session (SET rbi.audit_allow_drop = 'on') ; ne jamais le faire en production.
GUARD_DROP = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM audit_auditlog)
       AND current_setting('rbi.audit_allow_drop', true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'rbi: le journal d''audit contient des entrées ; retour arrière refusé';
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0001_row_level_security"),
    ]

    operations = [
        migrations.RunSQL(FUNCTIONS, DROP_FUNCTIONS),
        migrations.RunSQL(TABLES, DROP_TABLES),
        migrations.RunSQL(SEAL, DROP_SEAL),
        migrations.RunSQL(READERS, DROP_READERS),
        migrations.RunSQL(POLICIES, DROP_POLICIES),
        migrations.RunSQL(PRIVILEGES, migrations.RunSQL.noop),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigIntegerField(primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(verbose_name="horodatage (UTC, serveur PostgreSQL)")),
                (
                    "scope",
                    models.CharField(
                        choices=[("platform", "plateforme"), ("organization", "organisme")],
                        max_length=20,
                        verbose_name="portée",
                    ),
                ),
                ("organization_id", models.UUIDField(null=True, verbose_name="organisme concerné")),
                (
                    "actor_type",
                    models.CharField(
                        choices=[("user", "utilisateur"), ("anonymous", "anonyme"), ("system", "système")],
                        max_length=20,
                        verbose_name="type d'acteur",
                    ),
                ),
                ("actor_id", models.UUIDField(null=True, verbose_name="acteur")),
                ("action", models.CharField(max_length=64, verbose_name="action")),
                (
                    "outcome",
                    models.CharField(
                        choices=[("success", "succès"), ("denied", "refus"), ("failure", "échec")],
                        max_length=10,
                        verbose_name="résultat",
                    ),
                ),
                ("object_type", models.CharField(max_length=40, null=True, verbose_name="type d'objet")),
                ("object_id", models.CharField(max_length=64, null=True, verbose_name="identifiant d'objet")),
                ("old_value", models.JSONField(null=True, verbose_name="ancienne valeur")),
                ("new_value", models.JSONField(null=True, verbose_name="nouvelle valeur")),
                ("metadata", models.JSONField(verbose_name="métadonnées")),
                ("ip_address", models.GenericIPAddressField(null=True, verbose_name="adresse IP")),
                ("request_id", models.UUIDField(null=True, verbose_name="identifiant de requête")),
                ("prev_hash", models.CharField(max_length=64, verbose_name="empreinte précédente")),
                ("hash", models.CharField(max_length=64, verbose_name="empreinte")),
            ],
            options={
                "verbose_name": "entrée du journal d'audit",
                "verbose_name_plural": "journal d'audit",
                "db_table": "audit_auditlog",
                "ordering": ("id",),
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="AuditChain",
            fields=[
                ("chain_key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("last_id", models.BigIntegerField(null=True)),
                ("last_hash", models.CharField(max_length=64)),
                ("length", models.BigIntegerField()),
                ("updated_at", models.DateTimeField(null=True)),
            ],
            options={"db_table": "audit_chain", "managed": False},
        ),
        # Dernière opération : exécutée EN PREMIER lors d'un retour arrière.
        migrations.RunSQL(migrations.RunSQL.noop, GUARD_DROP),
    ]
