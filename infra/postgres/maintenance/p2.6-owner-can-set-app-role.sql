-- P2.6 — à exécuter UNE FOIS par le superutilisateur sur un cluster initialisé avant P2.6
-- (les nouveaux clusters le reçoivent du script initdb). Idempotent ; ne modifie aucune donnée.
--
--   docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres --       -v owner="$RBI_DB_OWNER" -v app="$RBI_DB_APP_USER"' < infra/postgres/maintenance/p2.6-owner-can-set-app-role.sql
--
-- Le propriétaire peut endosser le rôle applicatif (SET ROLE) sans hériter de ses droits ; le rôle applicatif
-- ne gagne rien. Utilisé par la suite de tests pour exécuter le code testé sous RLS.
SELECT format('GRANT %I TO %I WITH INHERIT FALSE, SET TRUE', :'app', :'owner') \gexec
