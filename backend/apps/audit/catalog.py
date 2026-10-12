"""Catalogue fermé des événements d'audit (§9.11, ADR 0009).

Seules les actions listées ici peuvent être enregistrées : une action inconnue est refusée (erreur de
programmation détectée par les tests), ce qui évite les fautes de frappe et les événements inventés. Les
événements des modules métier (alertes, rapports, exports, accès sous mandat…) seront ajoutés avec ces
modules : aucun n'est déclaré tant que la fonctionnalité n'existe pas.
"""

from __future__ import annotations

ACTIONS: dict[str, str] = {
    # --- Authentification et sessions (§9.11 : connexion, déconnexion, échec de connexion) -----------------
    "auth.login": "Connexion par mot de passe (succès : étape suivante ; échec ; refus)",
    "auth.session.open": "Ouverture d'une session complète",
    "auth.session.close": "Déconnexion",
    "auth.session.terminate": "Fermeture d'une session par la politique de session",
    "auth.reauthenticate": "Échec de confirmation du mot de passe pour une opération sensible",
    "auth.password.change": "Changement de mot de passe",
    "auth.password_reset.request": "Demande de réinitialisation du mot de passe",
    "auth.password_reset.confirm": "Réinitialisation du mot de passe par lien",
    "auth.sessions.revoke_others": "Fermeture des autres sessions",
    # --- MFA ----------------------------------------------------------------------------------------------
    "auth.mfa.enroll.start": "Début d'enrôlement TOTP",
    "auth.mfa.enroll.confirm": "Confirmation de l'enrôlement TOTP",
    "auth.mfa.verify": "Vérification d'un second facteur",
    "auth.mfa.renew.start": "Début de renouvellement TOTP",
    "auth.mfa.renew.confirm": "Confirmation du renouvellement TOTP",
    "auth.mfa.backup_codes.regenerate": "Régénération des codes de secours",
    "auth.mfa.disable": "Désactivation volontaire de la MFA",
    "auth.mfa.admin_reset": "Réinitialisation de la MFA par un Administrateur institutionnel",
    "auth.mfa.server_reset": "Réinitialisation de la MFA par commande serveur (maintenance)",
    # --- Contrôle d'accès ---------------------------------------------------------------------------------
    "rbac.check": "Refus d'une permission RBAC",
    "platform.scope": "Délivrance ou refus d'un périmètre plateforme",
    "tenant.access": "Refus du contexte d'organisme (organisme non actif)",
    # --- Organismes et demandes d'accès (§9.11 : changement de statut d'un organisme) ---------------------
    "access_request.submit": "Dépôt d'une demande d'accès (formulaire public)",
    "access_request.reject": "Rejet d'une demande d'accès",
    "organization.register": "Enregistrement d'un organisme",
    "organization.update": "Modification d'un organisme",
    "organization.transition": "Changement de statut d'un organisme",
    "organization.authorization.add": "Ajout d'une autorisation formelle",
    "organization.activate": "Refus d'activation d'un organisme",
    "organization.reactivate": "Refus de réactivation d'un organisme",
    # --- Comptes et rôles (§9.11 : création, modification, changement de permission) ----------------------
    "user.bootstrap_super_admin": "Création d'un Super Administrateur (maintenance)",
    "user.create_institutional_admin": "Désignation du premier Administrateur institutionnel",
    "user.create": "Création d'un compte",
    "user.role.assign": "Attribution d'un rôle",
    "user.role.revoke": "Retrait d'un rôle",
    "user.activate": "Activation d'un compte",
    "user.deactivate": "Désactivation d'un compte",
    "user.set_active": "Refus d'activation ou de désactivation d'un compte",
    # --- Journal d'audit lui-même (consultation sensible) -------------------------------------------------
    "audit.read": "Consultation du journal d'audit",
    "audit.export": "Export du journal d'audit (P2.8)",
    "audit.verify": "Vérification de l'intégrité d'une chaîne",
}

OBJECT_TYPES: frozenset[str] = frozenset(
    {"user", "organization", "organization_authorization", "access_request", "audit_chain"}
)
