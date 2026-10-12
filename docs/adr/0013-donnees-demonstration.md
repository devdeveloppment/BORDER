# ADR 0013 — Données fictives de démonstration (`seed_demo`, P2.11)

- **Statut** : proposée (implémentée sur validation de conception ; en attente de validation de P2.11)
- **Date** : 12/10/2026
- **Source** : spécification interne non publiée v1.0 §26 (données de démonstration) ; feuille de route P2 (P2.11) ; décisions D1 à
  D8 de la validation de conception P2.11 ; ADR 0005 (multi-organismes), 0006 (RBAC), 0007 (authentification et MFA),
  0008 (RLS), 0009 (audit), 0012 (intégration)

## Contexte

La spécification interne non publiée prévoit un générateur de données fictives pour les démonstrations. Une partie de son contenu
(postes frontaliers, activités, véhicules, événements, alertes, indicateurs) relève de modules qui n'existent pas
encore (P3 à P7). Ce générateur ne crée que ce que le modèle et les services existants gèrent.

## Décisions

### 1. Périmètre

Deux organismes fictifs (`Organisme Démo A` et `Organisme Démo B`, sigles `DEMO-A` et `DEMO-B`), leurs
autorisations, la séquence de statut `EN_ATTENTE → AUTORISEE → ACTIVE`, et cinq comptes par organisme, un par rôle
institutionnel (`ORG_ADMIN`, `SUPERVISOR`, `AGENT`, `ANALYST`, `AUDITOR`). Aucun modèle n'est créé pour les autres
entités. Les sources de données (`DataSource`) sont **exclues** : ni service, ni marqueur.

### 2. Écritures par les services uniquement

Chaque création passe par `register_organization`, `authorize_organization`, `create_institutional_admin`,
`activate_organization` et `create_organization_user`, sous un `PlatformScope` délivré par `platform_scope` pour
l'acteur désigné. Aucune écriture directe, aucun contournement de RLS ni de permission.

### 3. Acteur désigné, jamais créé

`--actor-email` désigne un compte existant, actif, sans organisme, qui détient `platform.organizations` et
`platform.institutional_admins`. La commande ne crée, ne promeut, ne modifie ni ne réinitialise jamais ce compte.

### 4. Marquage

- Organismes : `is_demo = true` et sigles déterministes. Un organisme homonyme sans marqueur fait refuser le lot.
- Comptes : adresses au domaine réservé `.test` (`admin@demo-a.rbi.test`, etc.). Un compte existant hors du jeu fait
  refuser le lot.
- Aucun champ n'est ajouté à `User` ni à `DataSource` (pas de migration).

### 5. Gardes-fous (avant toute écriture)

1. `RBI_ENV` doit valoir explicitement `development` ou `test`. Toute autre valeur, absente comprise, refuse.
2. Le rôle de base doit être le rôle applicatif ; le rôle propriétaire est refusé.
3. L'acteur doit être un Super Administrateur actif, vérifié par les mécanismes `platform_scope`.

### 6. Planification sans écriture, puis application transactionnelle

Le lot est vérifié en lecture seule : collisions, états inattendus, rôles différents. Toute anomalie refuse le lot,
sans modification. L'application s'exécute dans une seule transaction.

### 7. Comportement de l'audit

- Un succès dans une transaction est écrit au commit : un lot annulé ne laisse **aucun** événement de succès.
- Un refus est écrit immédiatement : il reste visible même si le lot est annulé.
- Les créations sont attribuées à leur auteur réel : l'acteur désigné pour les organismes et les administrateurs,
  l'administrateur de l'organisme pour ses comptes.

### 8. Pas de mot de passe, activation séparée

Les comptes sont créés sans mot de passe utilisable (`has_usable_password()` faux). La commande n'envoie aucun
courriel et ne génère aucun jeton. L'activation est une procédure manuelle, documentée dans le rapport P2.11 : « mot de
passe oublié », lien reçu dans la messagerie de développement, puis enrôlement MFA à la première connexion. Cette
séparation est prévue par la décision D5 : déclencher la réinitialisation depuis la commande exigerait une requête HTTP
factice (limitation par adresse IP et journal), ce qui n'est pas sûr.

## Conséquences

- Aucune migration, aucun privilège ajouté à `rbi_app`, aucun changement de l'API ni des politiques RLS.
- Relancer la commande est sans effet sur des données déjà présentes (idempotence vérifiée).
- Les données créées portent le marqueur de démonstration ; leur présence dans l'interface reste soumise au bandeau
  « Données de démonstration » déjà en place (P2.10).

## Limites

1. Pas de sources de données, postes, activités, véhicules, événements, alertes ni indicateurs : ces entités arrivent
   avec leurs modules (P3 à P7). Le scénario « Poste Démo 07 » et `demo_trigger` dépendent du module d'alertes.
2. Les comptes de démonstration ne sont pas activés par la commande (procédure manuelle).
3. La commande exige un Super Administrateur existant, créé séparément par `create_super_admin`.
4. Le marquage des comptes repose sur le domaine `.test` et le marqueur de l'organisme, sans champ dédié.
