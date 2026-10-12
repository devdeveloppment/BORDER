import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { useSession } from "@/lib/auth/session";
import { FULLY_MOCKED } from "@/lib/env";
import { AuthLayout } from "./AuthLayout";
import { rememberMfaStep } from "./mfaStep";

const DEMO_ACCOUNTS = [
  { email: "superviseur@demo-a.rbi.test", role: "Superviseur — Démo A (MFA)" },
  { email: "admin@demo-a.rbi.test", role: "Admin institutionnel — Démo A (MFA)" },
  { email: "agent@demo-a.rbi.test", role: "Agent — Démo A" },
  { email: "analyste@demo-a.rbi.test", role: "Analyste — Démo A" },
  { email: "auditeur@demo-a.rbi.test", role: "Auditeur — Démo A (MFA)" },
  { email: "superviseur@demo-b.rbi.test", role: "Superviseur — Démo B (MFA)" },
  { email: "superadmin@plateforme.rbi.test", role: "Super Administrateur (MFA)" },
];

/** Écran 6 — Connexion. Message d'erreur générique, sans indication sur l'existence du compte. */
export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const from = (location.state as { from?: string } | null)?.from ?? "/app";

  const mutation = useMutation({
    mutationFn: () => endpoints.login(email, password),
    onSuccess: async (res) => {
      // Session complète : la redirection a lieu de façon réactive dès que l'utilisateur est chargé.
      if (res.step === "AUTHENTICATED") await refresh();
      else {
        rememberMfaStep(res.step);
        navigate("/connexion/mfa", { state: { from, step: res.step } });
      }
    },
  });

  if (user) return <Navigate to={from} replace />;

  const error = mutation.error instanceof ApiError ? mutation.error : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <AuthLayout
      title="Connexion"
      subtitle="Accédez à l'espace de votre organisme."
      footer={
        // Comptes fictifs de la maquette : absents du bundle de production (condition évaluée à la construction).
        import.meta.env.VITE_APP_ENV !== "production" && FULLY_MOCKED ? (
          <details className="rounded-[var(--radius-card)] border border-white/15 bg-white/5 p-4 text-[12px] text-brand-50">
            <summary className="cursor-pointer font-semibold">Comptes de démonstration (API simulée — Phase 1)</summary>
            <p className="mt-2 text-brand-100/80">
              Mot de passe : <code className="rounded bg-white/10 px-1">Demo-RBI-2026!</code> — code MFA simulé : <code className="rounded bg-white/10 px-1">123456</code>
            </p>
            <ul className="mt-2 space-y-1">
              {DEMO_ACCOUNTS.map((a) => (
                <li key={a.email}>
                  <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => setEmail(a.email)}>
                    {a.email}
                  </button>{" "}
                  <span className="text-brand-100/70">— {a.role}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && (error.status === 401 || error.status === 403) ? (
          <Notice tone="warn">
            {error.status === 403 ? (error.problem?.detail ?? "L'accès de votre organisme est suspendu.") : "Identifiants incorrects."}
          </Notice>
        ) : mutation.isError ? (
          // 429 (verrouillage progressif, avec délai), réseau, service indisponible : message générique du client.
          <Notice tone="warn">{describeError(mutation.error)}</Notice>
        ) : null}
        <Field label="Adresse email" required>
          {(p) => <Input {...p} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label="Mot de passe" required>
          {(p) => <Input {...p} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <div className="flex justify-end">
          <Link to="/connexion/recuperation" className="text-[13px] font-medium text-brand-700 hover:underline">
            Mot de passe oublié ?
          </Link>
        </div>
        <Button type="submit" className="w-full" size="lg" loading={mutation.isPending} loadingLabel="Connexion…" disabled={!email || !password}>
          Se connecter
        </Button>
      </form>
    </AuthLayout>
  );
}
