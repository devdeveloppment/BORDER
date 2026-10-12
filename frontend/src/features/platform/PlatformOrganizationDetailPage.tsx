import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { Field, Input, Textarea } from "@/components/ui/form";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { OrganizationStatusAction, PlatformOrganizationDetail } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { formatDate, formatDateTime } from "@/lib/format";
import { ORG_STATUS_LABEL } from "@/lib/labels";
import { PERMISSIONS } from "@/lib/permissions";
import { ORG_STATUS_TONE, REGISTRY_KEY } from "./PlatformOrganizationsPage";

const STATUS_ACTIONS: { action: OrganizationStatusAction; label: string; from: PlatformOrganizationDetail["status"][]; reason: boolean; danger?: boolean }[] = [
  { action: "activate", label: "Activer", from: ["AUTORISEE"], reason: false },
  { action: "suspend", label: "Suspendre", from: ["ACTIVE"], reason: true, danger: true },
  { action: "reactivate", label: "Réactiver", from: ["SUSPENDUE"], reason: true },
  { action: "archive", label: "Archiver", from: ["AUTORISEE", "ACTIVE", "SUSPENDUE"], reason: true, danger: true },
];

/** Fiche d'un organisme (écran 31) : autorisations formelles, administrateur, cycle de vie (§9.16, P2.10). */
export function PlatformOrganizationDetailPage() {
  const { id = "" } = useParams();
  const key = ["platform-org", id];
  const { data: org, isLoading, error, refetch } = useQuery({ queryKey: key, queryFn: () => endpoints.platformOrganization(id) });

  if (error) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (isLoading || !org) return <LoadingBlock rows={8} />;

  return (
    <>
      <PageHeader
        title={org.name}
        breadcrumb={{ label: "Organismes", to: "/app/plateforme/organismes" }}
        description="Aucune donnée opérationnelle de l'organisme n'est accessible depuis la plateforme."
        actions={<Badge tone={ORG_STATUS_TONE[org.status]}>{ORG_STATUS_LABEL[org.status]}</Badge>}
      />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="Identité" />
          <CardBody>
            <DefinitionList
              items={[
                { label: "Raison sociale", value: org.name },
                { label: "Sigle", value: org.short_name },
                { label: "Nature", value: org.type },
                { label: "Pays", value: org.country_code },
                { label: "Fuseau horaire", value: org.timezone },
                { label: "Hébergement", value: org.deployment_mode === "mutualise" ? "Mutualisé (isolation logique + RLS)" : "Dédié" },
                { label: "Démonstration", value: org.is_demo ? "Oui (données fictives)" : "Non" },
                { label: "Conservation", value: `${org.retention_days} jours` },
                { label: "Comptes", value: org.users_count },
                { label: "Enregistré le", value: formatDateTime(org.created_at) },
              ]}
            />
          </CardBody>
        </Card>
        <StatusCard org={org} queryKey={key} />
        <AuthorizationsCard org={org} queryKey={key} />
        <AdminCard org={org} queryKey={key} />
      </div>
    </>
  );
}

function useRefresh(queryKey: unknown[]) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey });
    await queryClient.invalidateQueries({ queryKey: REGISTRY_KEY });
  };
}

function StatusCard({ org, queryKey }: { org: PlatformOrganizationDetail; queryKey: unknown[] }) {
  const refresh = useRefresh(queryKey);
  const [pending, setPending] = useState<OrganizationStatusAction | null>(null);
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: (action: OrganizationStatusAction) => endpoints.changeOrganizationStatus(org.id, action, reason || undefined),
    onSuccess: async () => {
      setPending(null);
      setReason("");
      await refresh();
    },
  });
  const available = STATUS_ACTIONS.filter((a) => a.from.includes(org.status));
  const current = STATUS_ACTIONS.find((a) => a.action === pending);
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;

  return (
    <Card>
      <CardHeader title="Statut" description="Activation : autorisation en vigueur et Administrateur institutionnel actif requis." />
      <CardBody className="space-y-3">
        {mutation.isError && !apiError?.fieldError("reason") ? <Notice tone="warn">{describeError(mutation.error)}</Notice> : null}
        {available.length === 0 ? <p className="text-[13px] text-ink-500">Aucun changement de statut possible depuis « {ORG_STATUS_LABEL[org.status]} ».</p> : null}
        {current?.reason ? (
          <Field label={`Motif — ${current.label.toLowerCase()} (conservé dans le journal d'audit)`} required error={apiError?.fieldError("reason")}>
            {(p) => <Textarea {...p} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {available.map((a) =>
            pending === a.action ? (
              <Button key={a.action} variant={a.danger ? "danger" : "primary"} loading={mutation.isPending} disabled={a.reason && !reason.trim()} onClick={() => mutation.mutate(a.action)}>
                Confirmer : {a.label.toLowerCase()}
              </Button>
            ) : (
              <Button key={a.action} variant="secondary" onClick={() => (a.reason ? setPending(a.action) : mutation.mutate(a.action))} loading={mutation.isPending && !a.reason}>
                {a.label}
              </Button>
            ),
          )}
          {pending ? (
            <Button variant="ghost" onClick={() => setPending(null)}>
              Annuler
            </Button>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function AuthorizationsCard({ org, queryKey }: { org: PlatformOrganizationDetail; queryKey: unknown[] }) {
  const refresh = useRefresh(queryKey);
  const [form, setForm] = useState({ reference: "", scope: "", valid_from: "", valid_until: "" });
  const mutation = useMutation({
    mutationFn: () => endpoints.addAuthorization(org.id, { ...form, valid_until: form.valid_until || null }),
    onSuccess: async () => {
      setForm({ reference: "", scope: "", valid_from: "", valid_until: "" });
      await refresh();
    },
  });
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };
  const closed = org.status === "ARCHIVEE";

  return (
    <Card>
      <CardHeader title="Autorisations formelles" description={org.status === "EN_ATTENTE" ? "La première autorisation fait passer l'organisme à « Autorisée »." : "Renouvellement ou avenant."} />
      <CardBody className="space-y-4">
        {org.authorizations.length === 0 ? (
          <p className="text-[13px] text-ink-500">Aucune autorisation enregistrée.</p>
        ) : (
          <ul className="divide-y divide-line text-[13px]">
            {org.authorizations.map((a) => (
              <li key={a.id} className="py-2">
                <p className="font-medium text-ink-900">{a.reference}</p>
                <p className="text-xs text-ink-500">
                  {formatDate(a.valid_from)} → {a.valid_until ? formatDate(a.valid_until) : "sans échéance"} · {a.scope}
                </p>
              </li>
            ))}
          </ul>
        )}
        {closed ? null : (
          <form onSubmit={submit} className="space-y-3 border-t border-line pt-4" noValidate>
            {mutation.isError && !apiError?.problem?.errors ? <Notice tone="warn">{describeError(mutation.error)}</Notice> : null}
            <Field label="Référence de la convention" required error={apiError?.fieldError("reference")}>
              {(p) => <Input {...p} value={form.reference} onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))} />}
            </Field>
            <Field label="Périmètre autorisé" required error={apiError?.fieldError("scope")}>
              {(p) => <Textarea {...p} value={form.scope} onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value }))} />}
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Valide du" required error={apiError?.fieldError("valid_from") ?? apiError?.fieldError("non_field_errors")}>
                {(p) => <Input {...p} type="date" value={form.valid_from} onChange={(e) => setForm((f) => ({ ...f, valid_from: e.target.value }))} />}
              </Field>
              <Field label="Valide jusqu'au" hint="Facultatif" error={apiError?.fieldError("valid_until")}>
                {(p) => <Input {...p} type="date" value={form.valid_until} onChange={(e) => setForm((f) => ({ ...f, valid_until: e.target.value }))} />}
              </Field>
            </div>
            <Button type="submit" loading={mutation.isPending} loadingLabel="Enregistrement…" disabled={!form.reference || !form.scope || !form.valid_from}>
              Enregistrer l'autorisation
            </Button>
          </form>
        )}
      </CardBody>
    </Card>
  );
}

function AdminCard({ org, queryKey }: { org: PlatformOrganizationDetail; queryKey: unknown[] }) {
  const { can } = useSession();
  const refresh = useRefresh(queryKey);
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "" });
  const mutation = useMutation({
    mutationFn: () => endpoints.designateInstitutionalAdmin(org.id, form),
    onSuccess: async () => {
      setForm({ email: "", first_name: "", last_name: "" });
      await refresh();
    },
  });
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;
  if (!can(PERMISSIONS.platformInstitutionalAdmins)) return null;
  const open = org.status === "AUTORISEE" || org.status === "ACTIVE";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <Card>
      <CardHeader title="Administrateur institutionnel" description="Premier administrateur de l'organisme : il gère ensuite lui-même les comptes." />
      <CardBody>
        {!open ? (
          <p className="text-[13px] text-ink-500">Désignation possible une fois l'organisme autorisé.</p>
        ) : (
          <form onSubmit={submit} className="space-y-3" noValidate>
            {mutation.isSuccess ? (
              <Notice tone="ok" title="Administrateur désigné">
                Compte {mutation.data.email} créé sans mot de passe : il le définit par « Mot de passe oublié » une fois l'organisme actif, puis active sa MFA.
              </Notice>
            ) : null}
            {mutation.isError && !apiError?.problem?.errors ? <Notice tone="warn">{describeError(mutation.error)}</Notice> : null}
            <Field label="Adresse email professionnelle" required error={apiError?.fieldError("email")}>
              {(p) => <Input {...p} type="email" autoComplete="off" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />}
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Prénom">{(p) => <Input {...p} value={form.first_name} onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))} />}</Field>
              <Field label="Nom">{(p) => <Input {...p} value={form.last_name} onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))} />}</Field>
            </div>
            <Button type="submit" loading={mutation.isPending} loadingLabel="Désignation…" disabled={!form.email}>
              Désigner l'administrateur
            </Button>
          </form>
        )}
      </CardBody>
    </Card>
  );
}
