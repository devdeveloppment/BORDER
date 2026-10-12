import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Notice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { TotpEnrollment } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";
import { ROLE_LABEL } from "@/lib/labels";
import { BackupCodesPanel } from "@/features/auth/components/BackupCodes";
import { TotpEnrollmentPanel } from "@/features/auth/components/TotpEnrollment";

/** Message d'échec d'une opération sensible : mot de passe actuel incorrect (401), politique (400), etc. */
function failure(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "Mot de passe actuel incorrect.";
  if (error instanceof ApiError && error.status === 400) {
    return error.fieldError("password") ?? error.fieldError("new_password") ?? (error.problem?.title === "Code invalide ou expiré" ? "Code invalide ou expiré." : describeError(error));
  }
  return describeError(error);
}

/** Confirmation par le mot de passe actuel (le backend la revérifie et compte les échecs comme à la connexion). */
function PasswordGate({ label, action, onConfirm, pending, error, danger }: { label: string; action: string; onConfirm: (password: string) => void; pending: boolean; error: string | null; danger?: boolean }) {
  const [password, setPassword] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onConfirm(password);
    setPassword("");
  };
  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      {error ? <Notice tone="warn">{error}</Notice> : null}
      <Field label={label} required>
        {(p) => <Input {...p} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
      </Field>
      <Button type="submit" variant={danger ? "danger" : "primary"} loading={pending} disabled={!password}>
        {action}
      </Button>
    </form>
  );
}

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="space-y-3 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <div>
        <h3 className="text-[13px] font-semibold text-ink-900">{title}</h3>
        {description ? <p className="text-xs text-ink-500">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** Écran 29 — Profil : identité (non modifiable) et sécurité du compte (P2.5, intégré en P2.10). */
export function ProfilePage() {
  const { user } = useSession();
  if (!user) return null;
  return (
    <>
      <PageHeader title="Mon profil" />
      <div className="grid max-w-4xl gap-5">
        <Card>
          <CardHeader title="Identité" />
          <CardBody>
            <DefinitionList
              items={[
                { label: "Nom", value: `${user.first_name} ${user.last_name}`.trim() || "—" },
                { label: "Email", value: user.email },
                { label: "Organisme", value: user.organization?.name ?? "Plateforme (niveau Super Administrateur)" },
                { label: "Rôle(s)", value: user.roles.map((r) => ROLE_LABEL[r]).join(", ") || "—" },
                { label: "Dernière connexion", value: user.last_login ? formatDateTime(user.last_login) : "—" },
              ]}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Mot de passe et sessions" />
          <CardBody className="space-y-4">
            <ChangePassword />
            <RevokeSessions />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Vérification en deux étapes" />
          <CardBody className="space-y-4">
            <DefinitionList
              items={[
                { label: "Authentification multifacteur", value: <Badge tone={user.mfa_enabled ? "ok" : "neutral"}>{user.mfa_enabled ? "Activée" : "Non activée"}</Badge> },
                { label: "MFA obligatoire pour votre rôle", value: user.mfa_required ? "Oui" : "Non" },
              ]}
            />
            <TotpRenewal enabled={user.mfa_enabled} />
            {user.mfa_enabled ? <RegenerateBackupCodes /> : null}
            {user.mfa_enabled && !user.mfa_required ? <DisableMfa /> : null}
          </CardBody>
        </Card>
      </div>
    </>
  );
}

function ChangePassword() {
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const mutation = useMutation({
    mutationFn: () => endpoints.changePassword(form.current, form.next),
    onSuccess: () => setForm({ current: "", next: "", confirm: "" }),
  });
  const mismatch = form.confirm.length > 0 && form.confirm !== form.next;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) mutation.mutate();
  };
  return (
    <Section title="Changer de mot de passe" description="Toutes vos autres sessions seront fermées ; celle-ci reste ouverte.">
      <form onSubmit={submit} className="space-y-3" noValidate>
        {mutation.isSuccess ? <Notice tone="ok">Mot de passe modifié. Vos autres sessions ont été fermées.</Notice> : null}
        {mutation.isError ? <Notice tone="warn">{failure(mutation.error)}</Notice> : null}
        <Field label="Mot de passe actuel" required>
          {(p) => <Input {...p} type="password" autoComplete="current-password" value={form.current} onChange={(e) => setForm((f) => ({ ...f, current: e.target.value }))} />}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Nouveau mot de passe" required hint="12 caractères minimum.">
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={form.next} onChange={(e) => setForm((f) => ({ ...f, next: e.target.value }))} />}
          </Field>
          <Field label="Confirmer le nouveau mot de passe" required error={mismatch ? "Les mots de passe ne correspondent pas." : null}>
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => setForm((f) => ({ ...f, confirm: e.target.value }))} />}
          </Field>
        </div>
        <Button type="submit" loading={mutation.isPending} disabled={!form.current || form.next.length < 12 || mismatch || !form.confirm}>
          Changer le mot de passe
        </Button>
      </form>
    </Section>
  );
}

function RevokeSessions() {
  const mutation = useMutation({ mutationFn: (password: string) => endpoints.revokeOtherSessions(password) });
  return (
    <Section title="Fermer mes autres sessions" description="Déconnecte tous vos autres navigateurs et appareils.">
      {mutation.isSuccess ? <Notice tone="ok">Vos autres sessions ont été fermées.</Notice> : null}
      <PasswordGate label="Mot de passe actuel" action="Fermer les autres sessions" onConfirm={(pw) => mutation.mutate(pw)} pending={mutation.isPending} error={mutation.isError ? failure(mutation.error) : null} />
    </Section>
  );
}

function TotpRenewal({ enabled }: { enabled: boolean }) {
  const { refresh } = useSession();
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const start = useMutation({ mutationFn: (password: string) => endpoints.renewTotp(password), onSuccess: setEnrollment });
  const confirm = useMutation({
    mutationFn: (code: string) => endpoints.confirmTotpRenewal(code),
    onSuccess: (res) => {
      setEnrollment(null);
      setCodes(res.backup_codes);
    },
  });
  const title = enabled ? "Renouveler mon application d'authentification" : "Activer la vérification en deux étapes";

  if (codes) {
    return (
      <Section title={title}>
        <BackupCodesPanel
          codes={codes}
          doneLabel="Terminer"
          onDone={() => {
            setCodes(null);
            void refresh();
          }}
        />
      </Section>
    );
  }
  return (
    <Section title={title} description={enabled ? "L'appareil actuel reste valide jusqu'à la confirmation du nouveau." : "Facultative pour votre rôle, recommandée."}>
      {enrollment ? (
        <TotpEnrollmentPanel enrollment={enrollment} pending={confirm.isPending} error={confirm.isError ? failure(confirm.error) : null} onSubmit={(code) => confirm.mutate(code)} />
      ) : (
        <PasswordGate label="Mot de passe actuel" action={enabled ? "Renouveler" : "Activer"} onConfirm={(pw) => start.mutate(pw)} pending={start.isPending} error={start.isError ? failure(start.error) : null} />
      )}
    </Section>
  );
}

function RegenerateBackupCodes() {
  const [codes, setCodes] = useState<string[] | null>(null);
  const mutation = useMutation({ mutationFn: (password: string) => endpoints.regenerateBackupCodes(password), onSuccess: (res) => setCodes(res.backup_codes) });
  return (
    <Section title="Codes de secours" description="Générer une nouvelle série révoque immédiatement les anciens codes.">
      {codes ? (
        <BackupCodesPanel codes={codes} doneLabel="Terminer" onDone={() => setCodes(null)} />
      ) : (
        <PasswordGate label="Mot de passe actuel" action="Générer de nouveaux codes" onConfirm={(pw) => mutation.mutate(pw)} pending={mutation.isPending} error={mutation.isError ? failure(mutation.error) : null} />
      )}
    </Section>
  );
}

function DisableMfa() {
  const { refresh } = useSession();
  const mutation = useMutation({ mutationFn: (password: string) => endpoints.disableMfa(password), onSuccess: () => void refresh() });
  return (
    <Section title="Désactiver la vérification en deux étapes" description="Possible uniquement si votre rôle ne l'exige pas.">
      <PasswordGate label="Mot de passe actuel" action="Désactiver" danger onConfirm={(pw) => mutation.mutate(pw)} pending={mutation.isPending} error={mutation.isError ? failure(mutation.error) : null} />
    </Section>
  );
}
