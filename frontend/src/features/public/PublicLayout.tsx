import { Menu, X } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const LINKS = [
  { to: "/#solution", label: "Solution" },
  { to: "/#fonctionnalites", label: "Fonctionnalités" },
  { to: "/#innovation", label: "Innovation" },
  { to: "/#securite", label: "Sécurité" },
];

export function PublicLayout() {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-dvh flex-col bg-white">
      <a href="#contenu" className="sr-only z-50 bg-white px-3 py-2 focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Aller au contenu
      </a>
      <header className="sticky top-0 z-30 border-b border-navy-800 bg-navy-900 text-white">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-md bg-brand-600 text-sm font-bold" aria-hidden="true">
              R
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-bold tracking-wide">RIZTECH</span>
              <span className="block text-[10px] font-medium tracking-wider text-brand-100 uppercase">Border Intelligence</span>
            </span>
          </Link>
          <nav aria-label="Navigation publique" className="ml-auto hidden items-center gap-1 md:flex">
            {LINKS.map((l) => (
              <a key={l.to} href={l.to} className="rounded-md px-3 py-2 text-[13px] font-medium text-brand-50/85 hover:text-white">
                {l.label}
              </a>
            ))}
            <NavLink to="/contact" className="rounded-md px-3 py-2 text-[13px] font-medium text-brand-50/85 hover:text-white">
              Contact
            </NavLink>
            <Link to="/connexion" className={cn(buttonVariants({ size: "sm" }), "ml-2")}>
              Se connecter
            </Link>
          </nav>
          <button type="button" className="ml-auto rounded-md p-2 md:hidden" aria-label={open ? "Fermer le menu" : "Ouvrir le menu"} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? <X className="size-5" aria-hidden="true" /> : <Menu className="size-5" aria-hidden="true" />}
          </button>
        </div>
        {open ? (
          <nav aria-label="Navigation publique mobile" className="border-t border-navy-800 px-4 pb-4 md:hidden">
            {LINKS.map((l) => (
              <a key={l.to} href={l.to} onClick={() => setOpen(false)} className="block rounded-md px-2 py-2.5 text-sm text-brand-50">
                {l.label}
              </a>
            ))}
            <Link to="/contact" onClick={() => setOpen(false)} className="block rounded-md px-2 py-2.5 text-sm text-brand-50">
              Contact
            </Link>
            <Link to="/connexion" className={cn(buttonVariants(), "mt-2 w-full")}>
              Se connecter
            </Link>
          </nav>
        ) : null}
      </header>
      <main id="contenu" tabIndex={-1} className="flex-1 focus:outline-none">
        <Outlet />
      </main>
      <footer className="border-t border-line bg-surface-alt">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-xs text-ink-500 sm:px-6">
          <p>© 2026 RIZTECH — RIZTECH Border Intelligence (RBI)</p>
          <p>Plateforme complémentaire — ne remplace aucun système existant et n'est connectée à aucun système gouvernemental.</p>
        </div>
      </footer>
    </div>
  );
}
