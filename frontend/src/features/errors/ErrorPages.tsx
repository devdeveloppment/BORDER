import { Compass, ShieldAlert } from "lucide-react";
import { Link } from "react-router";
import { buttonVariants } from "@/components/ui/button";

function ErrorLayout({ icon: Icon, code, title, text, to, cta }: { icon: typeof Compass; code: string; title: string; text: string; to: string; cta: string }) {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center px-4 py-16 text-center">
      <Icon className="mb-4 size-12 text-brand-600" aria-hidden="true" />
      <p className="text-sm font-semibold tracking-widest text-ink-500">{code}</p>
      <h1 className="mt-1 text-2xl font-semibold text-navy-900">{title}</h1>
      <p className="mt-2 text-ink-500">{text}</p>
      <Link to={to} className={buttonVariants({ className: "mt-6" })}>
        {cta}
      </Link>
    </div>
  );
}

export function NotFoundPage() {
  return <ErrorLayout icon={Compass} code="404" title="Page introuvable" text="L'adresse demandée n'existe pas ou a été déplacée." to="/" cta="Retour à l'accueil" />;
}

export function ForbiddenPage() {
  return (
    <ErrorLayout
      icon={ShieldAlert}
      code="403"
      title="Vous n'avez pas accès à cette ressource"
      text="Votre rôle ne permet pas d'afficher cet écran. Contactez l'administrateur de votre organisme si nécessaire."
      to="/app"
      cta="Retour au tableau de bord"
    />
  );
}
