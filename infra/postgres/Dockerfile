# PostgreSQL 16 + PostGIS — image construite sur l'image officielle `postgres`
# (mises à jour mineures de sécurité) avec PostGIS issu du dépôt PGDG déjà configuré.
# L'image `postgis/postgis:16-3.5` embarque encore PostgreSQL 16.9 sur Debian 11 : voir ADR 0003.
FROM postgres:16.15-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       "postgresql-16-postgis-3=3.6.*" \
       "postgresql-16-postgis-3-scripts=3.6.*" \
    && rm -rf /var/lib/apt/lists/*

COPY --chmod=0755 initdb/ /docker-entrypoint-initdb.d/
