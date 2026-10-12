import { Building2, ClipboardList, FileBarChart2, LayoutDashboard, LineChart, MapPin, ScrollText, Settings, ShieldCheck, Siren, Users, type LucideIcon } from "lucide-react";
import { PERMISSIONS, type Permission } from "@/lib/permissions";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  permission: Permission;
  end?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Navigation principale — les entrées non autorisées sont masquées (§11.5). */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Pilotage",
    items: [
      { to: "/app", label: "Tableau de bord", icon: LayoutDashboard, permission: PERMISSIONS.dashboardView, end: true },
      { to: "/app/alertes", label: "Alertes", icon: Siren, permission: PERMISSIONS.alertsView },
      { to: "/app/postes", label: "Postes", icon: MapPin, permission: PERMISSIONS.postsView },
      { to: "/app/activites", label: "Activités", icon: ClipboardList, permission: PERMISSIONS.activitiesView },
    ],
  },
  {
    label: "Analyse",
    items: [
      { to: "/app/analyse", label: "Analyse", icon: LineChart, permission: PERMISSIONS.analyticsView },
      { to: "/app/rapports", label: "Rapports", icon: FileBarChart2, permission: PERMISSIONS.reportsView },
    ],
  },
  {
    label: "Administration",
    items: [
      { to: "/app/admin/utilisateurs", label: "Utilisateurs", icon: Users, permission: PERMISSIONS.usersView },
      { to: "/app/admin/organisme", label: "Organisme", icon: Building2, permission: PERMISSIONS.organizationView },
      { to: "/app/admin/parametres", label: "Paramètres", icon: Settings, permission: PERMISSIONS.settingsView },
      { to: "/app/audit", label: "Journal d'audit", icon: ScrollText, permission: PERMISSIONS.auditView },
    ],
  },
  {
    label: "Plateforme",
    items: [
      { to: "/app/plateforme/organismes", label: "Organismes", icon: ShieldCheck, permission: PERMISSIONS.platformOrganizations },
      { to: "/app/plateforme/audit", label: "Journal d'audit plateforme", icon: ScrollText, permission: PERMISSIONS.platformAudit },
    ],
  },
];

