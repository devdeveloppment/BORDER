# Phase 1 — Socle UI/UX : rapport

**Date** : 08/10/2026 · **Périmètre** : design system, shell applicatif, écrans fondamentaux sur API simulée.

## 1. Réalisé

- **Design system** (§11.2) : jetons Tailwind 4 (`src/styles/index.css`), police Inter auto-hébergée, rayon 8 px,
  transitions ≤ 150 ms, `prefers-reduced-motion`. Les couleurs fonctionnelles sont toujours doublées d'une icône
  et d'un libellé ; des variantes « -ink » assombries garantissent le contraste AA du texte.
- **Composants** : Button, Card, Badge / LevelBadge / AlertStatusBadge, Field / Input / Select / Textarea,
  Skeleton / LoadingBlock / EmptyState / ErrorState / Notice, Dialog (et tiroir latéral), DropdownMenu, Tabs,
  DataTable responsive (tableau ≥ 768 px, cartes en dessous), KpiCard, Pagination, PageHeader, EChart.
- **Shell applicatif** : sidebar repliable, en-tête (organisme, période, recherche, notifications, profil),
  tiroir de menu mobile, lien d'évitement, bandeau permanent « DONNÉES DE DÉMONSTRATION » + « API simulée ».
- **Gardes** : authentification (MFA comprise), masquage des entrées non autorisées, écran 403 pour un accès
  direct par URL, redirection du Super Admin vers la vue plateforme (aucune donnée opérationnelle).
- **Contrat de données** `src/lib/api/types.ts` aligné sur le §14, client HTTP (cookie de session, CSRF,
  RFC 9457) ; l'organisme n'est **jamais** transmis par le client.
- **API simulée MSW** (`src/mocks`) : données fictives déterministes (2 organismes × 10 postes, 2 400 activités,
  73 alertes dont le scénario « Poste Démo 07 — 72/100 »), cloisonnement A/B (404 hors organisme),
  permissions par rôle (403), cycle de vie des alertes avec motif obligatoire, latence réaliste.
  Chaque réponse porte l'en-tête `X-RBI-Mock: true`. Le code MSW est chargé dynamiquement et **désactivé en production**.

## 2. Écrans disponibles

| Écran (§11.5) | Route | Remarques |
|---|---|---|
| 1–4 Accueil, solution, fonctionnalités, innovation | `/` (sections ancrées) | Contenu statique, aucune donnée opérationnelle |
| 5 Contact / demande d'accès | `/contact` | Validation champ par champ ; aucune création de compte |
| 6 Connexion | `/connexion` | Message générique, comptes démo affichés en mode simulé |
| 7 MFA | `/connexion/mfa` | TOTP 6 chiffres, code de secours |
| 8 Récupération | `/connexion/recuperation` (`?token=` pour l'étape 2) | Réponse identique que le compte existe ou non |
| 9 Tableau de bord | `/app` | 9 KPI vs période précédente, courbe, aperçu schématique des postes, alertes récentes, Situation du jour |
| 11–12 Activités | `/app/activites`, `/app/activites/:id` | Filtres dans l'URL, pagination serveur (50) |
| 13–14 Alertes | `/app/alertes`, `/app/alertes/:id` | Explication, décomposition du score, comparaison, traitement humain, historique |
| 15–16 Postes | `/app/postes`, `/app/postes/:id` | Vue tuiles (jumeau numérique) / tableau ; onglets POSTE → STATISTIQUES |
| 17 Analyse | `/app/analyse` | Période A vs B, heatmap jour × heure, classements |
| 19–20 Rapports | `/app/rapports` | Historique + boîte de génération |
| 21 Notifications | `/app/notifications` | Lu / non lu, priorités |
| 22 Journal d'audit | `/app/audit` | Lecture seule, détail ancienne / nouvelle valeur |
| 23 Utilisateurs | `/app/admin/utilisateurs` | Admin institutionnel uniquement |
| 25 Paramètres | `/app/admin/parametres` | Seuils versionnés, lecture seule hors Admin |
| Organisme | `/app/admin/organisme` | Identité et autorisation formelle |
| 29 Profil | `/app/profil` | |
| 31 Organismes (Super Admin) | `/app/plateforme/organismes` | Demandes en attente, statuts, conventions |
| 404 / 403 | `*` | |

Captures desktop et mobile : [`captures/`](captures/).

## 3. Tests exécutés (résultats réels)

| Suite | Commande | Résultat |
|---|---|---|
| TypeScript strict | `npm run typecheck` | 0 erreur |
| ESLint | `npm run lint` | 0 erreur |
| Vitest | `npm test` | **69 / 69** (6 fichiers) |
| Playwright | `npm run test:e2e` | **32 réussis, 4 ignorés, 0 échec** (desktop 1366×768, tablette 820×1180, mobile Pixel 7) — exécuté deux fois, stable |
| Build de production | `npm run build` | OK |

Couverture fonctionnelle des tests :
- **contrat de l'API simulée** : 401 sans session, message générique, MFA exigée, organisme dérivé de la session, 404 inter-organismes, filtre manipulé sans effet, Super Admin sans données opérationnelles, Auditeur sans action, Agent limité à ses alertes et à EXAMINÉE, motif obligatoire ;
- **navigation** : redirection non authentifiée, parcours complet login → MFA → tableau de bord **sans aller-retour de route**, déconnexion, menus selon les 4 rôles testés, 403 par URL directe, 404 ;
- **alerte scénarisée** : score 72 = 20 + 15 + 17 + 20, cycle NOUVELLE → EN COURS → EXAMINÉE avec motif, lecture seule pour l'Analyste ;
- **accessibilité** : axe-core WCAG 2.1 A/AA sur 17 écrans (jsdom) **et** sur navigateur réel avec contraste (Playwright), sans débordement horizontal sur les 3 formats, navigation au clavier ;
- **vocabulaire** (CA-12) : analyse statique de tout le code source (aucun « fraude », « suspect », « criminel », « infraction », « coupable »).

Les 4 tests ignorés sont attendus : le tiroir mobile n'existe pas en desktop, et le script de captures ne s'exécute qu'à la demande.

## 4. Problèmes détectés et corrigés pendant la phase

1. **Déconnexion inopérante** : `queryClient.clear()` détachait l'observateur de session. Ordre corrigé.
2. **Aller-retour `/app → /connexion → /app` après la MFA** (condition de course) : la redirection post-authentification est désormais réactive.
3. **Débordement horizontal** du tableau de bord (desktop et mobile) : grille KPI responsive, `grid-cols-1` (`minmax(0,1fr)`) sur les grilles.
4. **Zones défilantes non focalisables** au clavier (WCAG 2.1.1) : `tabIndex` + `role="region"`.
5. **Contraste insuffisant** dans la chaîne de valeur de l'accueil.
6. **Libellé accessible des graphiques écrasé** par ECharts.
7. **MSW embarqué dans le bundle initial** : chunk dédié chargé uniquement en mode simulé.
8. **Données simulées irréalistes** (deux périodes identiques une fois agrégées ; journée en cours comparée à une journée complète).

## 5. Limites assumées (pas de fausses fonctionnalités)

Les actions qui exigent le backend sont **visibles mais désactivées**, avec une infobulle indiquant la phase :
création de poste, saisie d'activité, export, invitation d'utilisateur (P2), téléchargement de rapport (P8).
La génération de rapport enregistre une demande « En attente » sans produire de fichier.
Le journal d'audit affiche « Intégrité de la chaîne : non vérifiée » (le chaînage SHA-256 est implémenté côté serveur en P2/P9).
L'aperçu des postes du tableau de bord est **schématique** ; la carte MapLibre / OpenStreetMap est l'objet de P4.
L'assistant d'import, les sources de données, les intégrations et System Health ne sont pas encore construits (P2+).

## 6. Points d'attention

- Bundle initial : 186 kB gzip + ECharts 199 kB gzip. Un découpage par route est recommandé en P3 (objectif < 3 s).
- Node 25 utilisé pendant le développement : recommandation Node 24 LTS (voir ADR 0002).
