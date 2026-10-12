import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { AuthStep, TotpEnrollment } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { AuthLayout } from "./AuthLayout";
import { BackupCodesPanel } from "./components/BackupCodes";
import { TotpEnrollmentPanel } from "./components/TotpEnrollment";
import { forgetMfaStep, recalledMfaStep } from "./mfaStep";

/** Échec d'une étape MFA : session expirée ou verrouillage (retour à la connexion), sinon message sur place. */
function mfaFailure(error: unknown): { message: string; restart: boolean } {
  if (error instanceof ApiError && error.status === 401) return { message: "Votre session a expiré.", restart: true };
  if (error instanceof ApiError && error.status === 429) {
    return { message: `${describeError(error)} Par sécurité, l'étape de connexion a été fermée.`, restart: true };
  }
  if (error instanceof ApiError && error.status === 400) return { message: "Code invalide ou expiré.", restart: false };
  return { message: describeError(error), restart: false };
}

function Restart({ message }: { message: string }) {
  return (
    <Notice tone="warn">
      {message}{" "}
      <Link to="/connexion" className="font-semibold underline">
        Reconnectez-vous
      </Link>
      .
    </Notice>
  );
}

/** Écran 7 — Second facteur : code TOTP ou code de secours, ou enrôlement à la première connexion (P2.10). */
export function MfaPage() {
  const location = useLocation();
  const { user, refresh } = useSession();
  const state = location.state as { from?: string; step?: AuthStep } | null;
  const step = state?.step ?? recalledMfaStep() ?? "MFA_REQUIRED";
  const from = state?.from ?? "/app";
  // Codes de secours de l'enrôlement : affichés avant d'entrer dans l'application, puis oubliés.
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);

  const finish = async () => {
    setBackupCodes(null);
    forgetMfaStep();
    await refresh();
  };

  if (user && !backupCodes) return <Navigate to={from} replace />;

  if (backupCodes) {
    return (
      <AuthLayout title="Codes de secours" subtitle="Votre second facteur est activé.">
        <BackupCodesPanel codes={backupCodes} onDone={() => void finish()} doneLabel="Accéder à l'application" />
      </AuthLayout>
    );
  }

  return step === "MFA_ENROLLMENT_REQUIRED" ? (
    <Enrollment onEnrolled={(codes) => (codes?.length ? setBackupCodes(codes) : void finish())} />
  ) : (
    <Verification onVerified={() => void finish()} />
  );
}

function Enrollment({ onEnrolled }: { onEnrolled: (codes: string[] | undefined) => void }) {
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null);
  const start = useMutation({ mutationFn: endpoints.startMfaEnrollment, onSuccess: setEnrollment });
  const verify = useMutation({
    mutationFn: (code: string) => endpoints.verifyMfa(code),
    onSuccess: (res) => {
      setEnrollment(null); // le secret n'est plus nécessaire : effacé de l'état de l'écran
      onEnrolled(res.backup_codes);
    },
  });
  const startFailure = start.isError ? mfaFailure(start.error) : null;
  const failure = verify.isError ? mfaFailure(verify.error) : null;

  return (
    <AuthLayout title="Activer la vérification en deux étapes" subtitle="Votre rôle exige un second facteur. Configurez votre application d'authentification.">
      {failure?.restart ? (
        <Restart message={failure.message} />
      ) : enrollment ? (
        <TotpEnrollmentPanel enrollment={enrollment} pending={verify.isPending} error={failure?.message ?? null} onSubmit={(code) => verify.mutate(code)} />
      ) : (
        <div className="space-y-4">
          {startFailure ? startFailure.restart ? <Restart message={startFailure.message} /> : <Notice tone="warn">{startFailure.message}</Notice> : null}
          <p className="text-[13px] text-ink-700">
            Un QR code va être généré pour votre compte. Il ne sera affiché qu'une fois : gardez votre téléphone à portée de main.
          </p>
          <Button className="w-full" size="lg" loading={start.isPending} loadingLabel="Préparation…" onClick={() => start.mutate()}>
            Commencer l'enrôlement
          </Button>
        </div>
      )}
    </AuthLayout>
  );
}

function Verification({ onVerified }: { onVerified: () => void }) {
  const [code, setCode] = useState("");
  const [backup, setBackup] = useState(false);
  const mutation = useMutation({ mutationFn: () => endpoints.verifyMfa(code.replace(/\s/g, "")), onSuccess: onVerified });
  const failure = mutation.isError ? mfaFailure(mutation.error) : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <AuthLayout
      title="Vérification en deux étapes"
      subtitle={backup ? "Saisissez l'un de vos codes de secours." : "Saisissez le code à 6 chiffres affiché par votre application d'authentification."}
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {failure ? failure.restart ? <Restart message={failure.message} /> : <Notice tone="warn">{failure.message}</Notice> : null}
        <Field label={backup ? "Code de secours" : "Code de vérification"} required>
          {(p) => (
            <Input
              {...p}
              value={code}
              onChange={(e) => setCode(backup ? e.target.value : e.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode={backup ? "text" : "numeric"}
              autoComplete="one-time-code"
              className="h-12 text-center text-lg tracking-[0.4em] tabular"
              maxLength={backup ? 20 : 6}
              autoFocus
            />
          )}
        </Field>
        <Button type="submit" className="w-full" size="lg" loading={mutation.isPending} loadingLabel="Vérification…" disabled={backup ? code.length < 8 : code.length !== 6}>
          Vérifier
        </Button>
        <button
          type="button"
          onClick={() => {
            setBackup((b) => !b);
            setCode("");
          }}
          className="w-full text-center text-[13px] font-medium text-brand-700 hover:underline"
        >
          {backup ? "Utiliser l'application d'authentification" : "Utiliser un code de secours"}
        </button>
      </form>
    </AuthLayout>
  );
}
