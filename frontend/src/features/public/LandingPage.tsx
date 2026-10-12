import { BellRing, Building2, CalendarClock, Eye, FileBarChart2, Fingerprint, GitBranch, Layers, Lock, Map, ScrollText, Scale, Sparkles, Target, UserCheck } from "lucide-react";
import { Link } from "react-router";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/cn";

const CHAIN = ["Données", "Centralisation", "Visualisation", "Analyse", "Détection d'anomalies", "Alertes", "Aide à la décision", "Rapports"];

const BENEFITS = [
  { icon: Eye, title: "Voir", text: "Vos activités frontalières sur une seule carte et des tableaux de bord consolidés." },
  { icon: BellRing, title: "Repérer", text: "Les situations inhabituelles plus tôt, grâce à des alertes priorisées et expliquées." },
  { icon: FileBarChart2, title: "Rendre compte", text: "Des rapports homogènes PDF, Excel ou CSV produits en quelques minutes." },
];

const MODULES = [
  { icon: Layers, title: "Dashboard central", text: "KPI, tendances, situation du jour, personnalisation par rôle." },
  { icon: Map, title: "Carte intelligente", text: "Postes, alertes et événements géolocalisés sur OpenStreetMap." },
  { icon: Building2, title: "Postes frontaliers", text: "Fiche complète : activité, alertes, historique, statistiques." },
  { icon: ScrollText, title: "Registre des activités", text: "Recherche, filtres combinables, export journalisé." },
  { icon: BellRing, title: "Alertes intelligentes", text: "10 types d'écarts, cycle de vie traçable, assignation." },
  { icon: Target, title: "Indicateurs explicables", text: "Score 0–100 décomposé facteur par facteur." },
  { icon: CalendarClock, title: "Analyse historique", text: "Comparaisons N / N-1, heatmaps jour × heure." },
  { icon: GitBranch, title: "API & intégrations", text: "API REST v1 documentée ; connecteurs sur autorisation uniquement." },
];

const INNOVATIONS = [
  { title: "Carte intelligente", text: "Où, quand, quelle activité, quelle évolution, quelles alertes — en une vue." },
  { title: "Indicateur explicable", text: "« Niveau ÉLEVÉ (72/100) principalement dû à une variation de +38 % du volume… »" },
  { title: "Early Warning", text: "Tendances inhabituelles signalées avant d'atteindre un seuil — à surveiller." },
  { title: "Jumeau numérique opérationnel", text: "Vue réseau de tous les postes : flux, capacité, alertes." },
  { title: "Situation du jour", text: "Synthèse quotidienne déterministe — ne constitue pas une décision." },
  { title: "Scénarios « what-if »", text: "Tester des hypothèses de volume ou de capacité — résultat indicatif." },
];

const SECURITY = [
  { icon: Building2, title: "Espaces isolés", text: "Chaque organisme autorisé dispose d'un espace cloisonné : utilisateurs, sources, données." },
  { icon: Fingerprint, title: "MFA & rôles", text: "Authentification multifacteur et contrôle d'accès par rôle (RBAC)." },
  { icon: ScrollText, title: "Audit infalsifiable", text: "Journal append-only chaîné : chaque action significative est tracée." },
  { icon: UserCheck, title: "Décision humaine", text: "RBI signale et explique. Il ne prend jamais de décision coercitive ou administrative." },
  { icon: Scale, title: "IA responsable", text: "Aucune biométrie, aucune identification de personnes, aucune prédiction criminelle." },
  { icon: Lock, title: "Accès autorisé uniquement", text: "Aucun organisme ni aucune source sans autorisation, convention et base légale." },
];

export function LandingPage() {
  return (
    <>
      <section className="relative overflow-hidden bg-navy-900 text-white">
        <svg aria-hidden="true" className="absolute inset-0 h-full w-full opacity-[0.12]" preserveAspectRatio="none" viewBox="0 0 800 400">
          {Array.from({ length: 14 }, (_, i) => (
            <path key={i} d={`M0 ${40 + i * 26} C 200 ${10 + i * 30}, 420 ${80 + i * 22}, 800 ${30 + i * 27}`} fill="none" stroke="#5aa2ef" strokeWidth="1" />
          ))}
          {[[160, 120], [310, 210], [470, 150], [620, 260], [540, 320], [240, 300]].map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="5" fill="#5aa2ef" />
          ))}
        </svg>
        <div className="relative mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 md:grid-cols-[1.25fr_1fr] md:py-24">
          <div>
            <p className="text-xs font-semibold tracking-[0.2em] text-brand-100 uppercase">RIZTECH Border Intelligence</p>
            <h1 className="mt-4 text-3xl leading-tight font-semibold tracking-tight sm:text-4xl lg:text-5xl">Transformer les données frontalières en décisions intelligentes.</h1>
            <p className="mt-5 max-w-xl text-base text-brand-50/85">
              Plateforme multi-organisations de visualisation, d'analyse et d'aide à la décision pour les opérations frontalières. Une couche intelligente complémentaire — la décision finale reste toujours humaine.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/contact" className={buttonVariants({ size: "lg" })}>
                Demander une démonstration
              </Link>
              <Link to="/connexion" className={cn(buttonVariants({ size: "lg", variant: "secondary" }), "border-white/30 bg-transparent text-white hover:bg-white/10")}>
                Se connecter
              </Link>
            </div>
          </div>
          <div className="self-center rounded-[var(--radius-card)] border border-white/15 bg-white/5 p-5 backdrop-blur">
            <p className="text-xs font-semibold tracking-widest text-brand-100 uppercase">Positionnement</p>
            <p className="mt-3 text-[15px] leading-relaxed text-white">
              RBI n'est pas un nouveau système douanier. C'est une couche intelligente complémentaire qui transforme les données auxquelles un organisme autorisé a légalement accès en indicateurs, alertes et rapports exploitables.
            </p>
            <p className="mt-4 flex items-center gap-2 text-xs text-brand-100">
              <Sparkles className="size-4" aria-hidden="true" /> Démonstrateur sur données fictives uniquement
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="benefits-title" className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <h2 id="benefits-title" className="sr-only">Bénéfices clés</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {BENEFITS.map((b) => (
            <div key={b.title} className="rounded-[var(--radius-card)] border border-line p-5">
              <b.icon className="size-6 text-brand-600" aria-hidden="true" />
              <h3 className="mt-3 text-base font-semibold text-navy-900">{b.title}</h3>
              <p className="mt-1 text-[13px] text-ink-500">{b.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="solution" aria-labelledby="solution-title" className="scroll-mt-20 bg-surface-alt">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <h2 id="solution-title" className="text-2xl font-semibold text-navy-900">De la donnée à la décision</h2>
          <p className="mt-2 max-w-3xl text-ink-500">
            RBI se positionne en aval des systèmes existants (SYDONIA, GUCE ou autres), qu'il ne remplace pas et auxquels il n'est pas connecté. Il centralise les données saisies, importées ou transmises par une interface autorisée, dans l'espace isolé de chaque organisme.
          </p>
          <ol className="mt-8 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            {CHAIN.map((step, i) => (
              <li key={step} className={cn("rounded-[var(--radius-card)] border px-3 py-3 text-center text-[13px] font-semibold", i === 0 || i === CHAIN.length - 1 ? "border-navy-900 bg-navy-900 text-white" : "border-brand-100 bg-white text-navy-900")}>
                <span className={cn("block text-[10px] font-medium", i === 0 || i === CHAIN.length - 1 ? "text-brand-100" : "text-ink-500")} aria-hidden="true">
                  {String(i + 1).padStart(2, "0")}
                </span>
                {step}
              </li>
            ))}
          </ol>
          <p className="mt-4 text-[13px] font-medium text-danger-ink">Décision finale : toujours humaine (personne habilitée).</p>
        </div>
      </section>

      <section id="fonctionnalites" aria-labelledby="features-title" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
        <h2 id="features-title" className="text-2xl font-semibold text-navy-900">Fonctionnalités</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {MODULES.map((m) => (
            <div key={m.title} className="rounded-[var(--radius-card)] border border-line p-4">
              <m.icon className="size-5 text-brand-600" aria-hidden="true" />
              <h3 className="mt-2 font-semibold text-navy-900">{m.title}</h3>
              <p className="mt-1 text-[13px] text-ink-500">{m.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="innovation" aria-labelledby="innovation-title" className="scroll-mt-20 bg-navy-900 text-white">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <h2 id="innovation-title" className="text-2xl font-semibold">Six innovations réalistes, explicables et sous contrôle humain</h2>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {INNOVATIONS.map((n, i) => (
              <div key={n.title} className="rounded-[var(--radius-card)] border border-white/15 bg-white/5 p-5">
                <p className="text-xs font-semibold text-brand-100">0{i + 1}</p>
                <h3 className="mt-1 font-semibold">{n.title}</h3>
                <p className="mt-1 text-[13px] text-brand-50/80">{n.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="securite" aria-labelledby="security-title" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-14 sm:px-6">
        <h2 id="security-title" className="text-2xl font-semibold text-navy-900">Sécurité, gouvernance et responsabilité</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SECURITY.map((s) => (
            <div key={s.title} className="flex gap-3 rounded-[var(--radius-card)] border border-line p-4">
              <s.icon className="mt-0.5 size-5 shrink-0 text-brand-600" aria-hidden="true" />
              <div>
                <h3 className="font-semibold text-navy-900">{s.title}</h3>
                <p className="mt-1 text-[13px] text-ink-500">{s.text}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-10 flex flex-col items-start justify-between gap-4 rounded-[var(--radius-card)] bg-brand-50 p-6 sm:flex-row sm:items-center">
          <div>
            <p className="text-lg font-semibold text-navy-900">Commencer par une démonstration sur données fictives</p>
            <p className="text-[13px] text-ink-500">Puis définir conjointement un projet pilote mesuré.</p>
          </div>
          <Link to="/contact" className={buttonVariants({ size: "lg" })}>
            Demander une démonstration
          </Link>
        </div>
      </section>
    </>
  );
}
