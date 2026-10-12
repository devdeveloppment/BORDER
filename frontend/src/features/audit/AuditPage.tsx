import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, ShieldCheck, ShieldQuestion, ShieldX } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlay";
import { DefinitionList, PageHeader, Pagination } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { AuditEntry, AuditOutcome, AuditQuery } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

type Scope = "organization" | "platform";

/** Catégories d'actions du catalogue d'audit du backend (apps/audit/catalog.py) : préfixes acceptés par `action`. */
const ACTION_FILTERS: Record<Scope, [string, string][]> = {
  organization: [
    ["", "Toutes les actions"],
    ["auth", "Authentification"],
    ["user", "Comptes et rôles"],
    ["rbac", "Contrôles d'accès refusés"],
    ["tenant", "Accès à l'organisme"],
    ["organization", "Organisme"],
    ["audit", "Consultation du journal"],
  ],
  platform: [
    ["", "Toutes les actions"],
    ["organization", "Cycle de vie des organismes"],
    ["access_request", "Demandes d'accès"],
    ["user", "Comptes"],
    ["platform", "Périmètre plateforme"],
    ["auth", "Authentification"],
    ["audit", "Consultation du journal"],
  ],
};

const OUTCOME_LABEL: Record<AuditOutcome, string> = { success: "Succès", denied: "Refus", failure: "Échec" };
const OUTCOME_TONE: Record<AuditOutcome, "ok" | "warn" | "danger"> = { success: "ok", denied: "warn", failure: "danger" };

function OutcomeBadge({ entry }: { entry: AuditEntry }) {
  const outcome: AuditOutcome = entry.outcome ?? (entry.result === "succes" ? "success" : "failure");
  return <Badge tone={OUTCOME_TONE[outcome]}>{OUTCOME_LABEL[outcome]}</Badge>;
}

function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Écran 22 — Journal d'audit (lecture seule) : de son organisme, ou de la plateforme (P2.8, P2.10). */
export function AuditPage({ scope }: { scope: Scope }) {
  const [filters, setFilters] = useState<Omit<AuditQuery, "page" | "page_size">>({ action: "", outcome: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const query = { ...filters, page, page_size: 50 };
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["audit", scope, query], queryFn: () => endpoints.audit(query, scope) });
  const integrity = useMutation({ mutationFn: () => endpoints.auditIntegrity(scope) });
  const exporter = useMutation({
    mutationFn: () => endpoints.auditExport(filters, scope),
    onSuccess: ({ blob, filename }) => saveFile(blob, filename),
  });

  const update = (patch: Partial<typeof filters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setPage(1);
  };
  const exportError = exporter.error instanceof ApiError && exporter.error.status === 400 ? exporter.error.fieldError("non_field_errors") : null;

  return (
    <>
      <PageHeader
        title={scope === "platform" ? "Journal d'audit plateforme" : "Journal d'audit"}
        description="Enregistrement en insertion seule des actions significatives, chaîné par empreintes SHA-256. Aucune modification n'est possible."
        actions={
          <>
            <Button variant="secondary" loading={integrity.isPending} loadingLabel="Vérification…" onClick={() => integrity.mutate()}>
              <ShieldCheck aria-hidden="true" /> Vérifier l'intégrité
            </Button>
            <Button variant="secondary" loading={exporter.isPending} loadingLabel="Export…" onClick={() => exporter.mutate()}>
              <Download aria-hidden="true" /> Exporter (CSV)
            </Button>
          </>
        }
      />

      {integrity.data ? (
        <Notice className="mb-4" tone={integrity.data.chain_integrity === "valide" ? "ok" : "warn"} title={`Intégrité de la chaîne : ${integrity.data.chain_integrity === "valide" ? "valide" : "rompue"}`}>
          <span className="inline-flex flex-wrap items-center gap-1.5" data-testid="audit-integrity">
            {integrity.data.chain_integrity === "valide" ? <ShieldCheck className="size-4" aria-hidden="true" /> : <ShieldX className="size-4" aria-hidden="true" />}
            {integrity.data.checked} entrée(s) vérifiée(s) le {formatDateTime(integrity.data.verified_at)}.
            {integrity.data.errors.length ? ` ${integrity.data.errors.length} anomalie(s) : ${integrity.data.errors.slice(0, 3).join(" ; ")}` : ""}
          </span>
          <span className="mt-1 block font-mono text-[11px] break-all">Empreinte de tête (à conserver hors de la base) : {integrity.data.head_hash}</span>
        </Notice>
      ) : integrity.isError ? (
        <Notice className="mb-4" tone="warn">{describeError(integrity.error)}</Notice>
      ) : (
        <Notice className="mb-4" title="Intégrité de la chaîne : non vérifiée">
          <span className="inline-flex items-center gap-1.5">
            <ShieldQuestion className="size-4" aria-hidden="true" /> La vérification complète recalcule chaque empreinte côté serveur : utilisez « Vérifier l'intégrité ».
          </span>
        </Notice>
      )}
      {exporter.isError ? (
        <Notice className="mb-4" tone="warn">{exportError ?? describeError(exporter.error)}</Notice>
      ) : null}

      <Card>
        <div className="flex flex-wrap items-end gap-3 border-b border-line p-4">
          <Select aria-label="Type d'action" value={filters.action} onChange={(e) => update({ action: e.target.value })} className="w-64">
            {ACTION_FILTERS[scope].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
          <Select aria-label="Résultat" value={filters.outcome} onChange={(e) => update({ outcome: e.target.value as AuditOutcome | "" })} className="w-44">
            <option value="">Tous les résultats</option>
            <option value="success">Succès</option>
            <option value="denied">Refus</option>
            <option value="failure">Échec</option>
          </Select>
          <label className="text-xs text-ink-500">
            Du
            <Input type="date" aria-label="Date de début" value={filters.date_from} onChange={(e) => update({ date_from: e.target.value })} className="mt-1 w-40" />
          </label>
          <label className="text-xs text-ink-500">
            Au (exclu)
            <Input type="date" aria-label="Date de fin (exclue)" value={filters.date_to} onChange={(e) => update({ date_to: e.target.value })} className="mt-1 w-40" />
          </label>
        </div>
        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <LoadingBlock className="p-4" rows={10} />
        ) : data.results.length === 0 ? (
          <EmptyState title="Aucune entrée pour ces critères" />
        ) : (
          <>
            <DataTable<AuditEntry>
              caption="Journal d'audit"
              rows={data.results}
              rowKey={(e) => String(e.id)}
              onRowClick={setSelected}
              columns={[
                { key: "at", header: "Horodatage", cell: (e) => <span className="tabular">{formatDateTime(e.created_at)}</span> },
                { key: "actor", header: "Utilisateur", cell: (e) => e.actor },
                {
                  key: "action",
                  header: "Action",
                  cell: (e) => (
                    <button
                      type="button"
                      className="font-mono text-xs text-brand-700 hover:underline"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        setSelected(e);
                      }}
                    >
                      {e.action}
                    </button>
                  ),
                },
                { key: "obj", header: "Objet", cell: (e) => e.object_repr || "—" },
                { key: "ip", header: "IP", cell: (e) => <span className="font-mono text-xs">{e.ip_address ?? "—"}</span> },
                { key: "res", header: "Résultat", cell: (e) => <OutcomeBadge entry={e} /> },
              ]}
              mobileCard={(e) => (
                <button type="button" onClick={() => setSelected(e)} className="block w-full px-4 py-3 text-left">
                  <p className="font-mono text-xs text-brand-700">{e.action}</p>
                  <p className="mt-0.5 text-[13px] text-ink-900">{e.object_repr || "—"}</p>
                  <p className="text-xs text-ink-500">
                    {formatDateTime(e.created_at)} · {e.actor}
                  </p>
                </button>
              )}
            />
            <Pagination page={data.page} pageSize={data.page_size} count={data.count} onPage={setPage} />
          </>
        )}
      </Card>
      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)} title="Détail de l'entrée d'audit" side="right">
        {selected ? (
          <div className="space-y-4">
            <DefinitionList
              items={[
                { label: "Identifiant", value: selected.id },
                { label: "Horodatage", value: formatDateTime(selected.created_at) },
                { label: "Utilisateur", value: selected.actor },
                { label: "Action", value: <span className="font-mono text-xs">{selected.action}</span> },
                { label: "Résultat", value: <OutcomeBadge entry={selected} /> },
                { label: "Objet", value: selected.object_repr || "—" },
                { label: "Adresse IP", value: selected.ip_address ?? "—" },
                { label: "Requête", value: <span className="font-mono text-[11px]">{selected.request_id ?? "—"}</span> },
              ]}
            />
            <div>
              <p className="text-xs font-medium text-ink-500">Ancienne valeur → nouvelle valeur · détails</p>
              <pre className="mt-1 overflow-x-auto rounded-md bg-surface-alt p-3 text-xs">
                {JSON.stringify({ avant: selected.old_value, apres: selected.new_value, details: selected.details ?? {} }, null, 2)}
              </pre>
            </div>
            <div>
              <p className="text-xs font-medium text-ink-500">Empreinte (SHA-256)</p>
              <p className="mt-1 font-mono text-[11px] break-all text-ink-700">{selected.hash}</p>
              {selected.prev_hash ? <p className="mt-1 font-mono text-[11px] break-all text-ink-500">Précédente : {selected.prev_hash}</p> : null}
            </div>
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
