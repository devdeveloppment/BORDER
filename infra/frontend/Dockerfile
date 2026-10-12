# syntax=docker/dockerfile:1
# Serveur de développement Vite (P2.10, ADR 0012) : DÉVELOPPEMENT UNIQUEMENT, derrière Nginx.
# Les sources sont montées depuis ./frontend ; node_modules vit dans un volume du conteneur (dépendances Linux,
# jamais celles de Windows), créé ici avec le bon propriétaire pour que le conteneur tourne sans root.
FROM node:24.19.0-alpine
RUN mkdir -p /app/node_modules && chown -R node:node /app
WORKDIR /app
USER node
EXPOSE 5173
CMD ["sh", "-c", "npm ci --no-audit --no-fund --loglevel=error && exec npx vite --host 0.0.0.0 --port 5173 --strictPort"]
