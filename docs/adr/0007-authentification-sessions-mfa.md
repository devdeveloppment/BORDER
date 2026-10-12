# ADR 0007 — Authentification, sessions et MFA (P2.5)

- **Statut** : acceptée (validation du propriétaire du projet, 08/10/2026) ; RLS des tables MFA : ADR 0008
- **Date** : 08/10/2026
- **Source** : spécification interne non publiée v1.0, §13 (session HttpOnly, django-otp), §15.1-15.2, §19.1, écrans 6, 7, 8, 23, 29 ;
  ADR 0004 à 0006 ; contrat du frontend P1 (`frontend/src/lib/api`)

## Décisions

### 1. Parcours en trois états, sans session Django avant la MFA

| État | Contenu de la session | Accès |
|---|---|---|
| anonyme | — | routes publiques |
| en attente de MFA | `rbi.auth.pending` : utilisateur, étape, horodatage, empreinte de sécurité ; 5 min | `/auth/mfa/enroll`, `/auth/mfa/verify`, `/auth/logout` |
| authentifié | `django.contrib.auth.login` (nouvelle clé), `rbi.auth.at`, `rbi.auth.mfa` | selon RBAC |

Un mot de passe correct ne suffit jamais lorsque la MFA est requise. `request.user` reste anonyme pendant l'étape
intermédiaire : aucune route ni aucun service protégé n'est atteignable. L'étape expire au bout de 5 minutes et devient
invalide si l'empreinte de sécurité change ou si le compte devient inutilisable.

### 2. Identité reconstruite à chaque requête

`RBIAuthBackend` (identifiant : e-mail, hachage Argon2) recharge l'utilisateur et refuse la session si le compte est
désactivé ou si l'organisme n'est plus ACTIVE. Il ne fournit **aucune** permission Django (`has_perm` → faux) :
l'autorisation reste exclusivement RBAC (ADR 0006). Les permissions sont recalculées à chaque requête.

### 3. Empreinte de sécurité (`User.security_stamp`)

Elle entre dans `get_session_auth_hash` (vérifiée par Django à chaque requête) et dans le jeton de réinitialisation.
Elle est renouvelée lors d'un changement ou d'une réinitialisation du mot de passe, d'une révocation des autres
sessions, d'une désactivation, et d'une réinitialisation, d'un renouvellement ou d'une désactivation de la MFA.
Toutes les sessions existantes et tous les liens émis deviennent invalides, quel que soit le stockage des sessions.
Lorsque l'utilisateur agit lui-même, sa session courante est conservée (`update_session_auth_hash`).

### 4. Sessions et cookies (§19.1)

- Stockage dans Redis, base dédiée (`sessions`, base 3), distincte du cache.
- **30 minutes d'inactivité**, avec expiration glissante (`SESSION_SAVE_EVERY_REQUEST`) ; **durée absolue de 12 h**
  (choix RBI, non précisé par la spécification interne non publiée) ; expiration à la fermeture du navigateur.
- Cookie `rbi_session` : `HttpOnly`, `SameSite=Strict`, `Secure` hors développement.
- `SessionPolicyMiddleware` ferme toute session qui n'a pas été ouverte par le parcours RBI, qui dépasse la durée
  absolue, ou dont la MFA est devenue obligatoire (rôle attribué en cours de session).
- Refus par défaut : `AuthenticationRequiredMiddleware` renvoie 401 sur toute vue non marquée `@public_endpoint`.
  Les routes publiques sont listées et vérifiées par un test (9 au total).

### 5. CSRF

Protection CSRF de Django appliquée à toutes les requêtes non sûres, **sans aucune exemption**, y compris la connexion.
Le jeton s'obtient par `GET /api/v1/auth/csrf`. Le cookie `csrftoken` (`SameSite=Strict`) n'est pas `HttpOnly` :
le frontend P1 le relit pour l'en-tête `X-CSRFToken`, ce qui est le fonctionnement prévu par Django. Un refus CSRF
renvoie un 403 au format RFC 9457, sans indiquer de cause technique.

### 6. Mots de passe

Argon2 (repli PBKDF2 uniquement pour vérifier d'anciens hachages). Politique : 12 caractères minimum, liste de
~20 000 mots de passe compromis fournie par Django (aucun service externe interrogé), mot de passe non entièrement
numérique, non similaire à l'identité. Changement : mot de passe actuel exigé. Réinitialisation (écran 8) : réponse
identique dans tous les cas ; lien à usage unique valable 30 minutes, lié à l'empreinte de sécurité ; envoi uniquement
pour un compte utilisable ; e-mails capturés par Mailpit en développement.

### 7. Limitation des tentatives (Redis, identifiants hachés par HMAC)

| Cible | Règle |
|---|---|
| Connexion, par identifiant soumis | 5 échecs → verrouillage progressif : 1, 2, 4… min, plafond 60 min (429 + `Retry-After`) |
| Connexion, par IP | 30 échecs en 15 min |
| MFA, par compte | 5 codes invalides → verrouillage de 15 min, étape intermédiaire détruite |
| Réinitialisation | 3 par heure et par identifiant, 20 par IP ; au-delà, réponse identique sans envoi |

Les règles s'appliquent de la même façon qu'un compte existe ou non. L'adresse IP est celle du pair TCP ;
`X-Forwarded-For` n'est pas pris en compte tant qu'aucun proxy de confiance n'est déclaré (Nginx, P2.10).

### 8. MFA (TOTP django-otp et codes de secours)

- Obligatoire pour SUPER_ADMIN, AUDITOR, ORG_ADMIN et SUPERVISOR (ADR 0006), facultative pour les autres rôles.
- Enrôlement à la première connexion (`MFA_ENROLLMENT_REQUIRED`) : appareil non confirmé, URI `otpauth://` et secret
  base32 renvoyés une seule fois (`no-store`), puis confirmation par un premier code valide.
- Vérification : tolérance d'un pas de 30 s ; code ancien refusé ; rejeu impossible (`last_t`) ; ralentissement de
  django-otp en plus du verrouillage RBI.
- 10 codes de secours à usage unique, stockés **hachés** (HMAC-SHA256). Les codes statiques de django-otp, conservés
  en clair, ne sont pas utilisés. Régénération sur mot de passe ; les anciens codes sont révoqués.
- Renouvellement : le nouvel appareil ne remplace l'ancien qu'une fois confirmé. Désactivation impossible pour un rôle
  à MFA obligatoire.
- Récupération : code de secours ; réinitialisation par l'Administrateur institutionnel pour son organisme (service
  `reset_user_mfa`, `users.manage`) ; commande serveur `reset_user_mfa` pour les comptes plateforme. Chaque
  réinitialisation ferme toutes les sessions.

### 9. Super Administrateur

Création uniquement par la commande serveur `create_super_admin`, jamais par HTTP (vérifié par test). La commande
applique la politique de mot de passe et refuse un e-mail existant. La MFA est exigée à la première connexion.

### 10. Contrat d'API (P1) et compléments

Endpoints conformes au frontend : `POST /auth/login`, `/auth/mfa/verify`, `/auth/logout`, `/auth/password-reset`,
`/auth/password-reset/confirm`, `GET /me`. Ajouts : `GET /auth/csrf`, `POST /auth/mfa/enroll`, `/auth/password/change`,
`/auth/sessions/revoke-others`, `/auth/mfa/totp/renew` (+ `/confirm`), `/auth/mfa/backup-codes`, `/auth/mfa/disable`.
Ce sont des vues Django JSON ; DRF et OpenAPI viendront en P2.8 (**fait** : vues DRF au comportement identique, ADR 0010). **Le frontend n'a pas été modifié.** En P2.10, il
faudra appeler `GET /auth/csrf` avant la connexion et ajouter l'écran d'enrôlement (QR code depuis `otpauth_uri`,
affichage unique des codes de secours).

## Limites

- **RLS non activé (P2.6)**. Les tables `otp_totp_totpdevice` et `authentication_mfa_backup_code` n'ont pas
  d'`organization_id` : elles relèvent d'un cloisonnement par utilisateur, à prendre en compte en P2.6.
- Secrets TOTP stockés en clair par django-otp : chiffrement au repos prévu en V1 (§19.1).
- Pas de liste ni de révocation unitaire des sessions (écran 29) : « fermer toutes les autres sessions » est disponible.
- Comptes créés par un administrateur : sans mot de passe utilisable ; l'invitation passe par le lien de
  réinitialisation. Un e-mail d'invitation dédié reste à faire.
- ~~Différence de temps de réponse résiduelle lors d'une demande de réinitialisation (envoi SMTP synchrone).~~
  Envoi par le worker Celery, même travail dans tous les cas.
- Journal d'audit encore applicatif (append-only en P2.7). **P2.7** : journal PostgreSQL append-only et chaîné,
  ADR 0009.
