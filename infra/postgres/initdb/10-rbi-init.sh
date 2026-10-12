#!/bin/bash
# Initialisation du cluster RBI (exécutée UNE SEULE FOIS, au premier démarrage sur un volume vide).
#
# Rôles :
#   $POSTGRES_USER   superutilisateur d'amorçage — jamais utilisé par l'application ;
#   $RBI_DB_OWNER    propriétaire de la base et des tables, utilisé UNIQUEMENT pour les migrations ;
#   $RBI_DB_APP_USER rôle applicatif (API, Celery) : non propriétaire, NOSUPERUSER, NOBYPASSRLS,
#                    donc réellement soumis aux politiques Row-Level Security (P2.6).
#
# template1 reçoit PostGIS et les privilèges par défaut : toute base créée ensuite
# (base `rbi`, bases de test pytest-django) hérite de la même configuration.
set -euo pipefail

: "${RBI_DB_NAME:?RBI_DB_NAME manquant}"
: "${RBI_DB_OWNER:?RBI_DB_OWNER manquant}"
: "${RBI_DB_OWNER_PASSWORD:?RBI_DB_OWNER_PASSWORD manquant}"
: "${RBI_DB_APP_USER:?RBI_DB_APP_USER manquant}"
: "${RBI_DB_APP_PASSWORD:?RBI_DB_APP_PASSWORD manquant}"

run_psql() {
  psql -v ON_ERROR_STOP=1 --no-psqlrc --username "$POSTGRES_USER" \
    -v owner="$RBI_DB_OWNER" -v owner_pw="$RBI_DB_OWNER_PASSWORD" \
    -v app="$RBI_DB_APP_USER" -v app_pw="$RBI_DB_APP_PASSWORD" \
    -v dbname="$RBI_DB_NAME" "$@"
}

echo "[rbi-init] rôles"
run_psql --dbname postgres <<'EOSQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEROLE CREATEDB NOREPLICATION',
              :'owner', :'owner_pw') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION NOINHERIT',
              :'app', :'app_pw') \gexec
-- P2.6 : le propriétaire peut endosser le rôle applicatif (SET ROLE) sans en hériter les droits. Utilisé par la
-- suite de tests pour exécuter le code testé sous rbi_app, donc sous RLS ; n'accorde rien au rôle applicatif.
SELECT format('GRANT %I TO %I WITH INHERIT FALSE, SET TRUE', :'app', :'owner') \gexec
-- Pas d'accès implicite à la base de maintenance ; le propriétaire en a besoin pour créer les bases de test.
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
SELECT format('GRANT CONNECT ON DATABASE postgres TO %I', :'owner') \gexec
EOSQL

echo "[rbi-init] template1 : PostGIS + privilèges par défaut"
run_psql --dbname template1 <<'EOSQL'
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app') \gexec
-- Les objets créés par le propriétaire (migrations) sont accessibles au rôle applicatif
-- en lecture/écriture de lignes uniquement : jamais ALTER, DROP, TRUNCATE, REFERENCES ni TRIGGER.
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
              :'owner', :'app') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I',
              :'owner', :'app') \gexec
EOSQL

echo "[rbi-init] base ${RBI_DB_NAME}"
run_psql --dbname postgres <<'EOSQL'
SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template1 ENCODING ''UTF8''', :'dbname', :'owner') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'dbname') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', :'dbname', :'app') \gexec
EOSQL

echo "[rbi-init] terminé"
