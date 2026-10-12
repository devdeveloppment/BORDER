import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlay";
import { PageHeader } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { AccessRequest, OrganizationCreate, OrganizationStatus, OrganizationType, PlatformOrganization } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { ORG_STATUS_LABEL } from "@/lib/labels";

export const ORG_STATUS_TONE: Record<OrganizationStatus, "neutral" | "brand" | "ok" | "warn"> = {
  EN_ATTENTE: "neutral",
  AUTORISEE: "brand",
  ACTIVE: "ok",
  SUSPENDUE: "warn",
  ARCHIVEE: "neutral",
};

const ORG_TYPES: [OrganizationType, string][] = [
  ["douane", "Douane"],
  ["recettes", "Recettes"],
  ["police", "Police aux frontières"],
  ["portuaire", "Autorité portuaire"],
  ["transport", "Transport"],
  ["autre", "Autre"],
];

export const REGISTRY_KEY = ["platform-orgs"] as const;

/** Écran 31 — Registre des organismes (Super Admin, P2.10 : API réelle). Aucune donnée opérationnelle. */
export function PlatformOrganizationsPage() {
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useQuery({ queryKey: REGISTRY_KEY, queryFn: endpoints.platformOrganizations });
  const [registering, setRegistering] = useState<AccessRequest | "blank" | null>(null);
  const [rejecting, setRejecting] = useState<AccessRequest | null>(null);

  return (
    <>
      <PageHeader
        title="Organismes"
        description="Cycle d'autorisation : demande → enregistrement → autorisation formelle → désignation de l'administrateur → activation."
        actions={
          <Button onClick={() => setRegistering("blank")}>
            <Plus aria-hidden="true" /> Enregistrer un organisme
          </Button>
        }
      />
      <Notice className="mb-5">
        Le Super Administrateur ne consulte aucune donnée opérationnelle des organismes, sauf accès sous mandat limité dans le temps et journalisé.
      </Notice>
      {error ? (
        <Card>
          <ErrorState error={error} onRetry={() => void refetch()} />
        </Card>
      ) : isLoading || !data ? (
        <LoadingBlock rows={8} />
      ) : (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Demandes en attente" />
            {data.access_requests.length === 0 ? (
              <EmptyState positive title="Aucune demande en attente" />
            ) : (
              <ul className="divide-y divide-line">
                {data.access_requests.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-[13px]">
                    <div>
                      <p className="font-medium text-ink-900">{r.organization_name}</p>
                      <p className="text-xs text-ink-500">
                        {r.requester_name} — {r.requester_role} · {r.email}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge>{r.request_type === "acces" ? "Accès" : "Démonstration"}</Badge>
                      <span className="text-xs text-ink-500">{formatDateTime(r.created_at)}</span>
                      <Button size="sm" onClick={() => setRegistering(r)}>
                        Enregistrer
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setRejecting(r)}>
                        Rejeter
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Organismes" />
            {data.organizations.length === 0 ? (
              <EmptyState title="Aucun organisme enregistré" />
            ) : (
              <DataTable<PlatformOrganization>
                caption="Organismes"
                rows={data.organizations}
                rowKey={(o) => o.id}
                onRowClick={(o) => navigate(`/app/plateforme/organismes/${o.id}`)}
                columns={[
                  { key: "name", header: "Organisme", cell: (o) => <span className="font-medium text-ink-900">{o.name}</span> },
                  { key: "type", header: "Nature", cell: (o) => o.type },
                  { key: "status", header: "Statut", cell: (o) => <Badge tone={ORG_STATUS_TONE[o.status]}>{ORG_STATUS_LABEL[o.status]}</Badge> },
                  { key: "ref", header: "Convention", cell: (o) => o.authorization_reference ?? "—" },
                  { key: "valid", header: "Validité", cell: (o) => (o.valid_from ? `${formatDate(o.valid_from)} → ${o.valid_until ? formatDate(o.valid_until) : "…"}` : "—") },
                  { key: "users", header: "Utilisateurs", numeric: true, cell: (o) => o.users_count },
                ]}
                mobileCard={(o) => (
                  <button type="button" onClick={() => navigate(`/app/plateforme/organismes/${o.id}`)} className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left">
                    <div>
                      <p className="text-[13px] font-medium text-ink-900">{o.name}</p>
                      <p className="text-xs text-ink-500">{o.authorization_reference ?? "—"}</p>
                    </div>
                    <Badge tone={ORG_STATUS_TONE[o.status]}>{ORG_STATUS_LABEL[o.status]}</Badge>
                  </button>
                )}
              />
            )}
          </Card>
        </div>
      )}
      <RegisterDialog
        key={registering === "blank" ? "blank" : (registering?.id ?? "closed")}
        source={registering}
        onClose={() => setRegistering(null)}
        onCreated={(id) => navigate(`/app/plateforme/organismes/${id}`)}
      />
      <RejectDialog request={rejecting} onClose={() => setRejecting(null)} />
    </>
  );
}

function RegisterDialog({ source, onClose, onCreated }: { source: AccessRequest | "blank" | null; onClose: () => void; onCreated: (id: string) => void }) {
  const queryClient = useQueryClient();
  const request = source && source !== "blank" ? source : null;
  const [form, setForm] = useState<Omit<OrganizationCreate, "access_request_id">>({
    name: request?.organization_name ?? "",
    short_name: "",
    type: "douane",
    country_code: "",
    timezone: "UTC",
    retention_days: 365,
    deployment_mode: "mutualise",
    is_demo: true,
  });
  const mutation = useMutation({
    mutationFn: () => endpoints.createOrganization({ ...form, access_request_id: request?.id ?? null }),
    onSuccess: async (org) => {
      await queryClient.invalidateQueries({ queryKey: REGISTRY_KEY });
      onClose();
      onCreated(org.id);
    },
  });
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };

  return (
    <Dialog open={!!source} onOpenChange={(o) => !o && onClose()} title="Enregistrer un organisme" description={request ? `Suite à la demande de ${request.requester_name}.` : "Statut initial : en attente d'autorisation."}>
      <form id="register-org" onSubmit={submit} className="space-y-4" noValidate>
        {mutation.isError && !apiError?.problem?.errors ? <Notice tone="warn">{describeError(mutation.error)}</Notice> : null}
        <Field label="Raison sociale" required error={apiError?.fieldError("name")}>
          {(p) => <Input {...p} value={form.name} onChange={(e) => set("name", e.target.value)} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Sigle" required error={apiError?.fieldError("short_name")}>
            {(p) => <Input {...p} value={form.short_name} onChange={(e) => set("short_name", e.target.value)} />}
          </Field>
          <Field label="Nature" required error={apiError?.fieldError("type")}>
            {(p) => (
              <Select {...p} value={form.type} onChange={(e) => set("type", e.target.value as OrganizationType)}>
                {ORG_TYPES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Code pays (ISO 3166-1, 2 lettres)" required error={apiError?.fieldError("country_code")}>
            {(p) => <Input {...p} maxLength={2} value={form.country_code} onChange={(e) => set("country_code", e.target.value.toUpperCase())} />}
          </Field>
          <Field label="Fuseau horaire (IANA)" required error={apiError?.fieldError("timezone")}>
            {(p) => <Input {...p} value={form.timezone} onChange={(e) => set("timezone", e.target.value)} />}
          </Field>
          <Field label="Conservation des données (jours)" required error={apiError?.fieldError("retention_days")}>
            {(p) => <Input {...p} type="number" min={1} value={form.retention_days} onChange={(e) => set("retention_days", Number(e.target.value))} />}
          </Field>
          <Field label="Mode d'hébergement" error={apiError?.fieldError("deployment_mode")}>
            {(p) => (
              <Select {...p} value={form.deployment_mode} onChange={(e) => set("deployment_mode", e.target.value as OrganizationCreate["deployment_mode"])}>
                <option value="mutualise">Mutualisé</option>
                <option value="dedie">Dédié</option>
              </Select>
            )}
          </Field>
        </div>
        <label className="flex items-center gap-2 text-[13px] text-ink-700">
          <input type="checkbox" className="size-4 accent-brand-600" checked={form.is_demo} onChange={(e) => set("is_demo", e.target.checked)} />
          Organisme de démonstration (données fictives)
        </label>
      </form>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Annuler
        </Button>
        <Button type="submit" form="register-org" loading={mutation.isPending} loadingLabel="Enregistrement…">
          Enregistrer
        </Button>
      </div>
    </Dialog>
  );
}

function RejectDialog({ request, onClose }: { request: AccessRequest | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () => endpoints.rejectAccessRequest(request!.id, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: REGISTRY_KEY });
      setReason("");
      onClose();
    },
  });
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;
  return (
    <Dialog open={!!request} onOpenChange={(o) => !o && onClose()} title="Rejeter la demande" description={request?.organization_name}>
      <div className="space-y-4">
        {mutation.isError && !apiError?.fieldError("reason") ? <Notice tone="warn">{describeError(mutation.error)}</Notice> : null}
        <Field label="Motif (conservé dans le journal d'audit)" required error={apiError?.fieldError("reason")}>
          {(p) => <Textarea {...p} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Annuler
          </Button>
          <Button variant="danger" disabled={!reason.trim()} loading={mutation.isPending} onClick={() => mutation.mutate()}>
            Rejeter
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
