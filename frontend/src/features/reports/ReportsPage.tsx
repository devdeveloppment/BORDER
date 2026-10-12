import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FilePlus2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlay";
import { PageHeader } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { ApiError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { Report, ReportType } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { formatDate, formatDateTime } from "@/lib/format";
import { REPORT_TYPE_LABEL } from "@/lib/labels";
import { PERMISSIONS } from "@/lib/permissions";

const STATUS: Record<Report["status"], { label: string; tone: "neutral" | "brand" | "ok" | "warn" }> = {
  en_attente: { label: "En attente", tone: "neutral" },
  en_cours: { label: "En cours", tone: "brand" },
  termine: { label: "Terminé", tone: "ok" },
  echec: { label: "Échec", tone: "warn" },
};

function isoDay(offset = 0): string {
  const d = new Date();
  d.setDate(d.getDate() - offset);
  return d.toISOString().slice(0, 10);
}

function GenerateDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<{ report_type: ReportType; period_start: string; period_end: string; format: Report["format"] }>({ report_type: "journalier", period_start: isoDay(1), period_end: isoDay(1), format: "PDF" });
  const mutation = useMutation({
    mutationFn: () => endpoints.generateReport(form),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      onOpenChange(false);
    },
  });
  const err = mutation.error instanceof ApiError ? mutation.error.problem?.errors : undefined;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Générer un rapport"
      description="La génération est asynchrone ; vous serez notifié à la fin."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Annuler
          </Button>
          <Button onClick={() => mutation.mutate()} loading={mutation.isPending} loadingLabel="Envoi…">
            Générer
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Type de rapport" className="sm:col-span-2">
          {(p) => (
            <Select {...p} value={form.report_type} onChange={(e) => setForm((f) => ({ ...f, report_type: e.target.value as ReportType }))}>
              {(Object.keys(REPORT_TYPE_LABEL) as ReportType[]).map((t) => (
                <option key={t} value={t}>
                  {REPORT_TYPE_LABEL[t]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Début">{(p) => <Input {...p} type="date" value={form.period_start} onChange={(e) => setForm((f) => ({ ...f, period_start: e.target.value }))} />}</Field>
        <Field label="Fin" error={err?.period_end?.[0] ?? null}>
          {(p) => <Input {...p} type="date" value={form.period_end} onChange={(e) => setForm((f) => ({ ...f, period_end: e.target.value }))} />}
        </Field>
        <Field label="Format" className="sm:col-span-2">
          {(p) => (
            <Select {...p} value={form.format} onChange={(e) => setForm((f) => ({ ...f, format: e.target.value as Report["format"] }))}>
              <option value="PDF">PDF</option>
              <option value="XLSX">Excel (.xlsx)</option>
              <option value="CSV">CSV</option>
            </Select>
          )}
        </Field>
      </div>
      <Notice className="mt-4">Le rapport contiendra uniquement les données de votre organisme, avec la mention « DONNÉES DE DÉMONSTRATION ». Production des fichiers : Phase 8.</Notice>
    </Dialog>
  );
}

/** Écrans 19–20 — Historique des rapports et lancement d'une génération. */
export function ReportsPage() {
  const { can } = useSession();
  const [open, setOpen] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["reports"], queryFn: endpoints.reports });

  return (
    <>
      <PageHeader
        title="Rapports"
        description="Rapports générés pour votre organisme. Chaque génération et téléchargement est journalisé."
        actions={
          can(PERMISSIONS.reportsGenerate) ? (
            <Button onClick={() => setOpen(true)}>
              <FilePlus2 aria-hidden="true" /> Nouveau rapport
            </Button>
          ) : null
        }
      />
      <Card>
        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <LoadingBlock className="p-4" rows={6} />
        ) : data.length === 0 ? (
          <EmptyState title="Aucun rapport généré" />
        ) : (
          <DataTable<Report>
            caption="Historique des rapports"
            rows={data}
            rowKey={(r) => r.id}
            columns={[
              { key: "title", header: "Titre", cell: (r) => <span className="font-medium text-ink-900">{r.title}</span> },
              { key: "type", header: "Type", cell: (r) => REPORT_TYPE_LABEL[r.report_type] },
              { key: "period", header: "Période", cell: (r) => <span className="tabular">{formatDate(r.period_start)} → {formatDate(r.period_end)}</span> },
              { key: "format", header: "Format", cell: (r) => <Badge>{r.format}</Badge> },
              { key: "author", header: "Auteur", cell: (r) => r.generated_by },
              { key: "date", header: "Généré le", cell: (r) => <span className="tabular">{formatDateTime(r.created_at)}</span> },
              { key: "status", header: "Statut", cell: (r) => <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge> },
              {
                key: "dl",
                header: "Fichier",
                cell: (r) => (
                  <Button variant="ghost" size="sm" disabled title="Téléchargement par URL signée : Phase 8" aria-label={`Télécharger ${r.title}`}>
                    <Download aria-hidden="true" />
                  </Button>
                ),
              },
            ]}
            mobileCard={(r) => (
              <div className="px-4 py-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[13px] font-medium text-ink-900">{r.title}</p>
                  <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  {r.format} · {formatDate(r.period_start)} → {formatDate(r.period_end)} · {r.generated_by}
                </p>
              </div>
            )}
          />
        )}
      </Card>
      {open ? <GenerateDialog open={open} onOpenChange={setOpen} /> : null}
    </>
  );
}
