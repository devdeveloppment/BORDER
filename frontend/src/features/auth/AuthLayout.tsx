import type { ReactNode } from "react";
import { Link } from "react-router";
import { DemoBanner } from "@/components/layout/DemoBanner";

export function AuthLayout({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-navy-900">
      <DemoBanner />
      <main id="contenu" className="flex flex-1 flex-col items-center justify-center px-4 py-10">
        <Link to="/" className="mb-6 flex items-center gap-2.5 text-white">
          <span className="grid size-9 place-items-center rounded-md bg-brand-600 font-bold" aria-hidden="true">
            R
          </span>
          <span className="leading-tight">
            <span className="block font-bold tracking-wide">RIZTECH</span>
            <span className="block text-[10px] font-medium tracking-wider text-brand-100 uppercase">Border Intelligence</span>
          </span>
        </Link>
        <div className="w-full max-w-[420px] rounded-[var(--radius-card)] bg-white p-6 shadow-xl sm:p-8">
          <h1 className="text-xl font-semibold text-navy-900">{title}</h1>
          {subtitle ? <p className="mt-1 text-[13px] text-ink-500">{subtitle}</p> : null}
          <div className="mt-6">{children}</div>
        </div>
        {footer ? <div className="mt-6 w-full max-w-[420px]">{footer}</div> : null}
        <p className="mt-6 max-w-[420px] text-center text-[11px] text-brand-100/70">
          Usage réservé aux utilisateurs autorisés des organismes habilités. Toute connexion est journalisée.
        </p>
      </main>
    </div>
  );
}
