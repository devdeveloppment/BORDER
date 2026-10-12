# syntax=docker/dockerfile:1
# Image backend RBI : Python 3.13 + bibliothèques géospatiales (GeoDjango / PostGIS).
# Dépendances installées depuis uv.lock (--frozen) : build reproductible.

FROM ghcr.io/astral-sh/uv:0.12.14 AS uv

FROM python:3.13.16-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:${PATH}"
# GDAL tire GEOS et PROJ ; aucune chaîne de compilation dans l'image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgdal36 libgeos-c1t64 libproj25 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 rbi \
    && useradd --system --uid 10001 --gid rbi --home-dir /app --shell /usr/sbin/nologin rbi
WORKDIR /app

# Dépendances d'exécution uniquement.
FROM base AS runtime-deps
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

# Développement / tests : ajoute le groupe `dev` (pytest, ruff, mypy).
FROM runtime-deps AS dev
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project
COPY --chown=rbi:rbi . /app
USER rbi

# Exécution (le serveur applicatif et le code Django arrivent en P2.2).
FROM runtime-deps AS runtime
COPY --chown=rbi:rbi . /app
USER rbi
