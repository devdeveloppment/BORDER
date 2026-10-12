# RIZTECH Border Intelligence (RBI)

> « Transformer les données frontalières en décisions intelligentes. »

Plateforme web multi-organisations de visualisation, d'analyse et d'aide à la décision pour les opérations
frontalières. RBI est une **couche complémentaire** : elle ne remplace aucun système existant (SYDONIA, GUCE…)
et **n'est connectée à aucun système gouvernemental**. Le prototype fonctionne **exclusivement sur des données fictives**.
La décision finale appartient toujours à une personne habilitée.

## État du projet

| Phase | Contenu | État |
|---|---|---|
| P0 | Analyse et architecture | ✅ validée |
| P1 | Design system, shell applicatif, écrans (API simulée MSW) | ✅ livrée — [rapport](docs/phases/phase-1/RAPPORT.md) |
| P2 | Backend Django, multi-tenant + RLS, auth/MFA, RBAC, audit | en cours — [suivi des sous-phases](docs/phases/phase-2/README.md) |

## Structure

```
rbi/
├─ frontend/   React 19 + TypeScript 6 + Vite 8 + Tailwind 4 (SPA)
├─ backend/    Django 5.2 LTS + DRF + Celery (Python 3.13, dépendances verrouillées par uv)
├─ infra/      images et scripts d'initialisation (PostgreSQL 16 + PostGIS)
├─ scripts/    outils de poste (génération du .env)
└─ docs/       ADR et rapports de phase (la spécification fonctionnelle n'est pas publiée)
```

## Pile intégrée (Phase 2)

Prérequis : Docker Desktop (Compose v2). Choix : [ADR 0003](docs/adr/0003-infrastructure-backend.md),
[ADR 0012](docs/adr/0012-integration-frontend-backend.md) ; commandes détaillées : [backend/README.md](backend/README.md).

```bash
py scripts/init_env.py        # crée ou complète .env (secrets aléatoires, jamais commité)
docker compose up -d --wait   # http://127.0.0.1:8080 : Nginx → frontend (Vite, rechargement à chaud) + API Django
                              # PostgreSQL/PostGIS, Redis, S3, worker Celery internes ; Mailpit : http://127.0.0.1:8025
docker compose --profile tools run --rm backend pytest
py scripts/e2e.py             # E2E réels dans un environnement Docker jetable (projet rbi-e2e), HTTP puis TLS
docker compose down           # arrêt (données conservées) ; `down -v` efface les volumes
```

Mode **intégré** : authentification, comptes, organisme, journal d'audit et plateforme utilisent l'API réelle ;
les modules métier non encore implémentés (tableau de bord, postes, activités, alertes, analyses, rapports,
notifications, paramètres) restent simulés et l'indiquent (« Données simulées — module non encore implémenté »).
Premier compte : `docker compose run --rm migrate python manage.py create_super_admin --email <adresse fictive>`.
Les invitations passent par « Mot de passe oublié » ; les e-mails sont visibles dans Mailpit.
Débogage (ports directs des services) : `docker compose -f docker-compose.yml -f infra/compose.host-ports.yml up -d`.

## Frontend seul, API simulée (maquette Phase 1)

Prérequis : **Node.js 24 LTS** (`.nvmrc`, `engines: ^24.0.0`). Avec nvm-windows : `nvm install 24 && nvm use 24`.

```bash
cd frontend
cp .env.example .env      # VITE_API_MOCKS=true : tout simulé ; deferred : intégré ; false : API réelle seule
npm ci
npm run dev               # http://localhost:5173
```

Comptes de démonstration (mode tout simulé uniquement) : mot de passe `Demo-RBI-2026!`, code MFA `123456`.
La liste est affichée sur l'écran de connexion (ex. `superviseur@demo-a.rbi.test`).

## Qualité

```bash
npm run typecheck   # TypeScript strict
npm run lint        # ESLint
npm test            # Vitest : unitaires, contrat API, navigation, rôles, accessibilité, vocabulaire
npm run test:e2e    # Playwright (maquette, tout simulé) : desktop / tablette / mobile, axe-core, responsive
py ../scripts/e2e.py # Playwright (pile intégrée réelle) : parcours, MFA, audit, isolation, CSP, TLS
```

## Principes non négociables

Cloisonnement strict par organisme · décision humaine · explicabilité de chaque score · vocabulaire neutre
(jamais « fraude », « suspect »…) · traçabilité · aucune donnée réelle hors production autorisée.
