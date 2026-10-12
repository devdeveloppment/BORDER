import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";
import { AuthLayout } from "./AuthLayout";

/** Écran 8 — Récupération : demande de lien, puis définition du mot de passe (lien à usage unique, 30 min). */
export function RecoveryPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  // Jeton lu une fois puis retiré de l'URL (historique, en-tête Referer) ; il ne vit plus que dans l'état.
  const [token] = useState(() => params.get("token"));
  useEffect(() => {
    if (params.has("token")) navigate("/connexion/recuperation", { replace: true });
  }, [params, navigate]);
  return token ? <ResetForm token={token} /> : <RequestForm />;
}

function RequestForm() {
  const [email, setEmail] = useState("");
  const mutation = useMutation({ mutationFn: () => endpoints.requestPasswordReset(email) });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };
  return (
    <AuthLayout title="Mot de passe oublié" subtitle="Indiquez votre adresse email professionnelle.">
      {mutation.isSuccess ? (
        // Réponse identique que le compte existe ou non (pas d'énumération des comptes)
        <Notice tone="ok" title="Demande prise en compte">
          Si un compte correspond à cette adresse, un lien de réinitialisation valable 30 minutes vient d'être envoyé.
        </Notice>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          {mutation.isError ? <Notice tone="warn">{describeError(mutation.error)}</Notice> : null}
          <Field label="Adresse email" required>
            {(p) => <Input {...p} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />}
          </Field>
          <Button type="submit" className="w-full" size="lg" loading={mutation.isPending} loadingLabel="Envoi…" disabled={!email}>
            Envoyer le lien
          </Button>
        </form>
      )}
      <Link to="/connexion" className="mt-4 block text-center text-[13px] font-medium text-brand-700 hover:underline">
        Retour à la connexion
      </Link>
    </AuthLayout>
  );
}

function passwordStrength(pw: string): { score: number; label: string } {
  let score = 0;
  if (pw.length >= 12) score++;
  if (pw.length >= 16) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const label = pw.length < 12 ? "Trop court (12 caractères minimum)" : score >= 5 ? "Robuste" : score >= 3 ? "Correct" : "Faible";
  return { score, label };
}

function ResetForm({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const mutation = useMutation({ mutationFn: () => endpoints.confirmPasswordReset(token, password) });
  const strength = passwordStrength(password);
  const mismatch = confirm.length > 0 && confirm !== password;
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) mutation.mutate();
  };

  return (
    <AuthLayout title="Définir un nouveau mot de passe">
      {mutation.isSuccess ? (
        <>
          <Notice tone="ok" title="Mot de passe mis à jour">Vous pouvez maintenant vous connecter.</Notice>
          <Link to="/connexion" className="mt-4 block text-center text-[13px] font-medium text-brand-700 hover:underline">
            Aller à la connexion
          </Link>
        </>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          {mutation.isError ? (
            <Notice tone="warn">
              {apiError?.status === 400
                ? (apiError.fieldError("password") ?? "Ce lien est expiré ou invalide. Faites une nouvelle demande.")
                : describeError(mutation.error)}
            </Notice>
          ) : null}
          <Field label="Nouveau mot de passe" required hint={password ? `Robustesse : ${strength.label}` : "12 caractères minimum."}>
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
          </Field>
          <div className="flex gap-1" aria-hidden="true">
            {Array.from({ length: 5 }, (_, i) => (
              <span key={i} className={cn("h-1.5 flex-1 rounded-full", i < strength.score ? (strength.score >= 5 ? "bg-ok" : strength.score >= 3 ? "bg-brand-600" : "bg-warn") : "bg-line")} />
            ))}
          </div>
          <Field label="Confirmer le mot de passe" required error={mismatch ? "Les mots de passe ne correspondent pas." : null}>
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
          </Field>
          <Button type="submit" className="w-full" size="lg" loading={mutation.isPending} loadingLabel="Enregistrement…" disabled={password.length < 12 || mismatch || !confirm}>
            Définir le mot de passe
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
