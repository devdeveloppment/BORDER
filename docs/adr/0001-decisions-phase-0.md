# ADR 0001 — Décisions de cadrage (Phase 0)

- **Statut** : acceptée (validation du propriétaire du projet, 08/10/2026)
- **Source fonctionnelle** : *Spécification interne non publiée RBI v1.0* (octobre 2026)

| # | Décision | Écart à la spécification interne non publiée |
|---|---|---|
| P1 | Projet hors dossier synchronisé, chemin ASCII | — |
| P2 | Backend et services (PostgreSQL/PostGIS, Redis, MinIO, Mailpit, Celery) sous Docker Compose | — |
| P3 | React 19 + Tailwind 4 | La spécification interne non publiée cite React 18 — écart mineur, voir ADR 0002 |
| P4 | Pas de Pandas / NumPy / Scikit-learn en MVP : ORM Django, SQL PostgreSQL, Python standard | Le §13 les citait ; Isolation Forest reste V2 |
| P5 | Row-Level Security PostgreSQL dès P2 | Classée V1 dans le §12.3 — avancée |
| P6 | P1 construite sur mocks typés MSW, clairement signalés, remplacés progressivement par l'API réelle | — |
| P7 | Git, branche `main`, un commit par phase validée ; dépôt distant décidé plus tard | — |
| P8 | Coordonnées et données exclusivement fictives | — |
| P9 | Superviseur : visibilité sur tout l'organisme, restreignable aux postes affectés | Précise une ambiguïté du §7.2 |
| P10 | Import interdit à l'Agent par défaut, activable via `imports.run` | Résout l'incohérence §7.3 / écran 26 |
| P11 | Tuiles OSM publiques pour la démonstration, aucun service payant | — |
| P12 | Mailpit en dev/démo, aucun SMTP réel sans autorisation | — |
