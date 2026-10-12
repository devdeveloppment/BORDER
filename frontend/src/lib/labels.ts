import type {
  ActivityType,
  AlertStatus,
  AlertType,
  DataSourceType,
  Level,
  OrganizationStatus,
  PeriodKey,
  PostStatus,
  PostType,
  ReportType,
  RoleCode,
} from "./api/types";

/**
 * Libellés de l'interface. Vocabulaire contrôlé (spécification interne non publiée §17.3) :
 * uniquement « comportement inhabituel », « écart statistique », « anomalie détectée »,
 * « indicateur nécessitant une vérification ». Un test automatisé vérifie l'absence des termes interdits.
 */

export const LEVEL_LABEL: Record<Level, string> = {
  NORMAL: "Normal",
  ATTENTION: "Attention",
  ELEVE: "Élevé",
  CRITIQUE: "Critique",
};

export function levelFromScore(score: number): Level {
  if (score >= 90) return "CRITIQUE";
  if (score >= 70) return "ELEVE";
  if (score >= 40) return "ATTENTION";
  return "NORMAL";
}

export const ALERT_STATUS_LABEL: Record<AlertStatus, string> = {
  NOUVELLE: "Nouvelle",
  EN_COURS: "En cours",
  EXAMINEE: "Examinée",
  CONFIRMEE: "Confirmée",
  ECARTEE: "Écartée",
  CLOTUREE: "Clôturée",
};

export const ALERT_TYPE_LABEL: Record<AlertType, string> = {
  VOLUME_INHABITUEL: "Volume inhabituel",
  FREQUENCE_INHABITUELLE: "Fréquence inhabituelle",
  TEMPS_PASSAGE: "Temps de passage inhabituel",
  VARIATION_HISTORIQUE: "Variation vs historique",
  CONCENTRATION_TEMPORELLE: "Concentration temporelle",
  INCOHERENCE_DONNEES: "Incohérence de données",
  CHANGEMENT_COMPORTEMENT: "Changement de profil d'activité",
  REPETITION_ANORMALE: "Répétition inhabituelle",
  ANOMALIE_GEOGRAPHIQUE: "Anomalie géographique",
  SEUIL_CONFIGURE: "Seuil configuré dépassé",
};

export const ROLE_LABEL: Record<RoleCode, string> = {
  SUPER_ADMIN: "Super Administrateur",
  ORG_ADMIN: "Administrateur institutionnel",
  SUPERVISOR: "Superviseur",
  AGENT: "Agent opérationnel",
  ANALYST: "Analyste",
  AUDITOR: "Auditeur",
};

export const ORG_STATUS_LABEL: Record<OrganizationStatus, string> = {
  EN_ATTENTE: "En attente",
  AUTORISEE: "Autorisée",
  ACTIVE: "Active",
  SUSPENDUE: "Suspendue",
  ARCHIVEE: "Archivée",
};

export const ACTIVITY_TYPE_LABEL: Record<ActivityType, string> = {
  passage: "Passage",
  controle: "Contrôle",
  operation: "Opération",
  autre: "Autre",
};

export const POST_TYPE_LABEL: Record<PostType, string> = {
  terrestre: "Terrestre",
  portuaire: "Portuaire",
  aeroportuaire: "Aéroportuaire",
  autre: "Autre",
};

export const POST_STATUS_LABEL: Record<PostStatus, string> = {
  actif: "Actif",
  inactif: "Inactif",
  ferme_temporairement: "Fermé temporairement",
};

export const SOURCE_TYPE_LABEL: Record<DataSourceType, string> = {
  manuelle: "Saisie manuelle",
  fichier: "Import fichier",
  api: "API autorisée",
  connecteur: "Connecteur",
};

export const REPORT_TYPE_LABEL: Record<ReportType, string> = {
  journalier: "Journalier",
  hebdomadaire: "Hebdomadaire",
  mensuel: "Mensuel",
  activite: "Activité",
  alertes: "Alertes",
  poste: "Par poste",
  statistique: "Statistique",
  personnalise: "Personnalisé",
};

export const PERIOD_LABEL: Record<PeriodKey, string> = {
  today: "Aujourd'hui",
  "7d": "7 derniers jours",
  "30d": "30 derniers jours",
  "90d": "Trimestre (90 j)",
  "365d": "12 derniers mois",
};
