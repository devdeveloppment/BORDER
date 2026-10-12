import { useQuery } from "@tanstack/react-query";
import { Bell, ChevronsLeft, ChevronsRight, LogOut, Menu, Search, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { Dialog, DropdownContent, DropdownItem, DropdownLabel, DropdownMenu, DropdownSeparator, DropdownTrigger } from "@/components/ui/overlay";
import { endpoints } from "@/lib/api/endpoints";
import type { PeriodKey } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { PERIOD_LABEL, ROLE_LABEL } from "@/lib/labels";
import { usePeriod } from "@/lib/period";
import { PERMISSIONS } from "@/lib/permissions";
import { DemoBanner } from "./DemoBanner";
import { SimulatedModuleNotice } from "./SimulatedModuleNotice";
import { NAV_GROUPS } from "./nav";

function Brand({ compact }: { compact?: boolean }) {
  return (
    <Link to="/app" className="flex items-center gap-2.5 rounded-md px-1 py-1 text-white">
      <span className="grid size-8 shrink-0 place-items-center rounded-md bg-brand-600 text-sm font-bold" aria-hidden="true">
        R
      </span>
      {compact ? <span className="sr-only">RBI — accueil</span> : (
        <span className="leading-tight">
          <span className="block text-sm font-bold tracking-wide">RBI</span>
          <span className="block text-[10px] font-medium tracking-wider text-brand-100 uppercase">Border Intelligence</span>
        </span>
      )}
    </Link>
  );
}

function SideNav({ collapsed, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const { can } = useSession();
  return (
    <nav aria-label="Navigation principale" className="flex-1 space-y-5 overflow-y-auto px-2 py-4">
      {NAV_GROUPS.map((group) => {
        const items = group.items.filter((item) => can(item.permission));
        if (items.length === 0) return null;
        return (
          <div key={group.label}>
            {!collapsed ? <p className="mb-1.5 px-3 text-[10px] font-semibold tracking-widest text-brand-100/70 uppercase">{group.label}</p> : null}
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium text-brand-50/85 transition-colors duration-150 hover:bg-navy-800 hover:text-white",
                        isActive && "bg-brand-600 text-white hover:bg-brand-600",
                        collapsed && "justify-center px-0",
                      )
                    }
                  >
                    <item.icon className="size-[18px] shrink-0" aria-hidden="true" />
                    <span className={collapsed ? "sr-only" : undefined}>{item.label}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function UnreadBell() {
  const { data } = useQuery({ queryKey: ["notifications"], queryFn: endpoints.notifications, staleTime: 30_000 });
  const unread = data?.filter((n) => !n.read_at).length ?? 0;
  return (
    <Link
      to="/app/notifications"
      className="relative grid size-9 place-items-center rounded-md text-ink-700 hover:bg-surface-alt"
      aria-label={unread ? `Notifications — ${unread} non lue(s)` : "Notifications"}
    >
      <Bell className="size-5" aria-hidden="true" />
      {unread ? (
        <span aria-hidden="true" className="tabular absolute -top-0.5 -right-0.5 min-w-4.5 rounded-full bg-danger px-1 text-center text-[10px] leading-4.5 font-semibold text-white">
          {unread > 9 ? "9+" : unread}
        </span>
      ) : null}
    </Link>
  );
}

export function AppShell() {
  const { user, can, logout } = useSession();
  const { period, setPeriod } = usePeriod();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [search, setSearch] = useState("");

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    if (search.trim()) navigate(`/app/activites?search=${encodeURIComponent(search.trim())}`);
  };

  const onLogout = async () => {
    await logout();
    navigate("/connexion", { replace: true });
  };

  const orgName = user?.organization?.name ?? "Plateforme RBI";
  const showPeriod = location.pathname === "/app";

  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#contenu" className="sr-only z-50 bg-white px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Aller au contenu
      </a>
      <DemoBanner />
      <div className="flex min-h-0 flex-1">
        <aside className={cn("sticky top-0 hidden h-dvh shrink-0 flex-col bg-navy-900 lg:flex", collapsed ? "w-16" : "w-60")}>
          <div className={cn("flex h-14 items-center border-b border-navy-800 px-3", collapsed && "justify-center px-0")}>
            <Brand compact={collapsed} />
          </div>
          <SideNav collapsed={collapsed} />
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="flex items-center justify-center gap-2 border-t border-navy-800 py-3 text-xs text-brand-100/80 hover:text-white"
            aria-label={collapsed ? "Déplier la navigation" : "Replier la navigation"}
            aria-expanded={!collapsed}
          >
            {collapsed ? <ChevronsRight className="size-4" aria-hidden="true" /> : <><ChevronsLeft className="size-4" aria-hidden="true" /> Replier</>}
          </button>
        </aside>

        <Dialog open={mobileOpen} onOpenChange={setMobileOpen} title="Menu" side="left">
          <div className="-mx-5 -my-4 flex min-h-full flex-col bg-navy-900">
            <div className="border-b border-navy-800 px-3 py-3">
              <Brand />
            </div>
            <SideNav onNavigate={() => setMobileOpen(false)} />
          </div>
        </Dialog>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-white/95 px-3 backdrop-blur sm:gap-3 sm:px-5">
            <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Ouvrir le menu">
              <Menu aria-hidden="true" />
            </Button>
            <div className="flex min-w-0 items-center gap-2">
              <span className="grid size-8 shrink-0 place-items-center rounded-md bg-brand-50 text-xs font-bold text-brand-700" aria-hidden="true">
                {(user?.organization?.short_name ?? "RBI").slice(0, 2)}
              </span>
              <div className="min-w-0 leading-tight">
                <p className="truncate text-[13px] font-semibold text-navy-900" data-testid="org-name">
                  {orgName}
                </p>
                <p className="hidden truncate text-[11px] text-ink-500 sm:block">Espace organisationnel isolé</p>
              </div>
            </div>

            <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
              {showPeriod && can(PERMISSIONS.dashboardView) ? (
                <label className="hidden items-center gap-2 md:flex">
                  <span className="sr-only">Période</span>
                  <Select value={period} onChange={(e) => setPeriod(e.target.value as PeriodKey)} className="h-9 w-44 text-[13px]">
                    {(Object.keys(PERIOD_LABEL) as PeriodKey[]).map((p) => (
                      <option key={p} value={p}>
                        {PERIOD_LABEL[p]}
                      </option>
                    ))}
                  </Select>
                </label>
              ) : null}
              {can(PERMISSIONS.activitiesView) ? (
                <form role="search" onSubmit={onSearch} className="relative hidden xl:block">
                  <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-500" aria-hidden="true" />
                  <input
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Rechercher une référence…"
                    aria-label="Recherche globale par référence"
                    className="h-9 w-64 rounded-[var(--radius-card)] border border-line bg-surface-alt pr-3 pl-8 text-[13px] focus-visible:bg-white"
                  />
                </form>
              ) : null}
              <UnreadBell />
              <DropdownMenu>
                <DropdownTrigger asChild>
                  <button type="button" className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-surface-alt" aria-label="Menu du profil">
                    <span className="grid size-8 place-items-center rounded-full bg-navy-900 text-xs font-semibold text-white" aria-hidden="true">
                      {user ? `${user.first_name[0] ?? ""}${user.last_name[0] ?? ""}` || (user.email[0] ?? "?").toUpperCase() : "?"}
                    </span>
                  </button>
                </DropdownTrigger>
                <DropdownContent>
                  <DropdownLabel>
                    <p className="text-sm font-semibold text-ink-900">
                      {user && (user.first_name || user.last_name) ? `${user.first_name} ${user.last_name}` : user?.email}
                    </p>
                    <p className="text-xs text-ink-500">{user?.roles.map((r) => ROLE_LABEL[r]).join(", ")}</p>
                  </DropdownLabel>
                  <DropdownSeparator />
                  <DropdownItem onSelect={() => navigate("/app/profil")}>
                    <UserRound aria-hidden="true" /> Mon profil
                  </DropdownItem>
                  <DropdownItem onSelect={() => void onLogout()}>
                    <LogOut aria-hidden="true" /> Se déconnecter
                  </DropdownItem>
                </DropdownContent>
              </DropdownMenu>
            </div>
          </header>

          <main id="contenu" tabIndex={-1} className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-5 focus:outline-none sm:px-6 lg:py-6">
            <SimulatedModuleNotice />
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
