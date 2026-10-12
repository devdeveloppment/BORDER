import type { ReactNode } from "react";
import type { RouteObject } from "react-router";
import { AppShell } from "@/components/layout/AppShell";
import { ActivitiesPage } from "@/features/activities/ActivitiesPage";
import { ActivityDetailPage } from "@/features/activities/ActivityDetailPage";
import { OrganizationPage } from "@/features/admin/OrganizationPage";
import { SettingsPage } from "@/features/admin/SettingsPage";
import { UsersPage } from "@/features/admin/UsersPage";
import { AlertDetailPage } from "@/features/alerts/AlertDetailPage";
import { AlertsPage } from "@/features/alerts/AlertsPage";
import { AnalysisPage } from "@/features/analysis/AnalysisPage";
import { AuditPage } from "@/features/audit/AuditPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { MfaPage } from "@/features/auth/MfaPage";
import { RecoveryPage } from "@/features/auth/RecoveryPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { NotFoundPage } from "@/features/errors/ErrorPages";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { PlatformOrganizationDetailPage } from "@/features/platform/PlatformOrganizationDetailPage";
import { PlatformOrganizationsPage } from "@/features/platform/PlatformOrganizationsPage";
import { PostDetailPage } from "@/features/posts/PostDetailPage";
import { PostsPage } from "@/features/posts/PostsPage";
import { ProfilePage } from "@/features/profile/ProfilePage";
import { ContactPage } from "@/features/public/ContactPage";
import { LandingPage } from "@/features/public/LandingPage";
import { PublicLayout } from "@/features/public/PublicLayout";
import { ReportsPage } from "@/features/reports/ReportsPage";
import { PERMISSIONS as P, type Permission } from "@/lib/permissions";
import { HomeRedirect, RequireAuth, RequirePermission } from "./guards";

const guard = (permission: Permission, element: ReactNode) => <RequirePermission permission={permission}>{element}</RequirePermission>;

export const routes: RouteObject[] = [
  {
    element: <PublicLayout />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/contact", element: <ContactPage /> },
    ],
  },
  { path: "/connexion", element: <LoginPage /> },
  { path: "/connexion/mfa", element: <MfaPage /> },
  { path: "/connexion/recuperation", element: <RecoveryPage /> },
  {
    path: "/app",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <HomeRedirect>{guard(P.dashboardView, <DashboardPage />)}</HomeRedirect> },
      { path: "alertes", element: guard(P.alertsView, <AlertsPage />) },
      { path: "alertes/:id", element: guard(P.alertsView, <AlertDetailPage />) },
      { path: "postes", element: guard(P.postsView, <PostsPage />) },
      { path: "postes/:id", element: guard(P.postsView, <PostDetailPage />) },
      { path: "activites", element: guard(P.activitiesView, <ActivitiesPage />) },
      { path: "activites/:id", element: guard(P.activitiesView, <ActivityDetailPage />) },
      { path: "analyse", element: guard(P.analyticsView, <AnalysisPage />) },
      { path: "rapports", element: guard(P.reportsView, <ReportsPage />) },
      { path: "notifications", element: <NotificationsPage /> },
      { path: "audit", element: guard(P.auditView, <AuditPage scope="organization" />) },
      { path: "admin/utilisateurs", element: guard(P.usersView, <UsersPage />) },
      { path: "admin/organisme", element: guard(P.organizationView, <OrganizationPage />) },
      { path: "admin/parametres", element: guard(P.settingsView, <SettingsPage />) },
      { path: "plateforme/organismes", element: guard(P.platformOrganizations, <PlatformOrganizationsPage />) },
      { path: "plateforme/organismes/:id", element: guard(P.platformOrganizations, <PlatformOrganizationDetailPage />) },
      { path: "plateforme/audit", element: guard(P.platformAudit, <AuditPage scope="platform" />) },
      { path: "profil", element: <ProfilePage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
];

