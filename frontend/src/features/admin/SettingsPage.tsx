import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { ApiError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { OrganizationSettings } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";
import { PERMISSIONS } from "@/lib/permissions";

/** Écran 25 — Paramètres de l'organisme. Chaque enregistrement crée une nouvelle version. */
export function SettingsPage() {
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });
  if (error) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (isLoading || !data) return <LoadingBlock rows={10} />;
  return <SettingsForm data={data} />;
}

function SettingsForm({ data }: { data: OrganizationSettings }) {
  const { can } = useSession();
  const editable = can(PERMISSIONS.settingsManage);
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(data.thresholds.map((t) => [t.code, String(t.value)])));
  const [retention, setRetention] = useState(String(data.retention_days));
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      endpoints.updateSettings({
        thresholds: Object.entries(values).map(([code, v]) => ({ code, value: Number(v) })),
        retention_days: Number(retention),
        comment,
      }),
    onSuccess: (next) => {
      setSaved(true);
      setComment("");
      queryClient.setQueryData(["settings"], next);
    },
  });
  const fieldErrors = mutation.error instanceof ApiError ? mutation.error.problem?.errors : undefined;

  return (
    <>
      <PageHeader title="Paramètres" description={`Version ${data.version} — modifiée le ${formatDateTime(data.updated_at)} par ${data.updated_by}`} />
      {!editable ? <Notice className="mb-4">Consultation en lecture seule : seul l'administrateur institutionnel peut modifier ces paramètres.</Notice> : null}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]"
      >
        <div className="space-y-5">
          <Card>
            <CardHeader title="Seuils d'alertes" description="Appliqués par le moteur de détection de votre organisme" />
            <CardBody className="grid gap-4 sm:grid-cols-2">
              {data.thresholds.map((t) => (
                <Field key={t.code} label={t.label} hint={`Unité : ${t.unit}`}>
                  {(p) => <Input {...p} type="number" min={0} step="any" value={values[t.code] ?? ""} disabled={!editable} onChange={(e) => setValues((v) => ({ ...v, [t.code]: e.target.value }))} />}
                </Field>
              ))}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Pondérations du moteur d'indicateurs" description="Barème maximal par facteur (versionné — modification en Phase 6)" />
            <CardBody>
              <DefinitionList items={data.risk_weights.map((w) => ({ label: w.label, value: `${w.max_points} points max` }))} />
            </CardBody>
          </Card>
        </div>
        <div className="space-y-5">
          <Card>
            <CardHeader title="Conservation et identité" />
            <CardBody className="space-y-4">
              <Field label="Durée de rétention (jours)" error={fieldErrors?.retention_days?.[0] ?? null}>
                {(p) => <Input {...p} type="number" min={1} value={retention} disabled={!editable} onChange={(e) => setRetention(e.target.value)} />}
              </Field>
              <DefinitionList
                items={[
                  { label: "Nom", value: data.identity.name },
                  { label: "Fuseau horaire", value: data.timezone },
                ]}
              />
            </CardBody>
          </Card>
          {editable ? (
            <Card>
              <CardHeader title="Enregistrer une nouvelle version" />
              <CardBody className="space-y-3">
                <Field label="Commentaire de version">{(p) => <Input {...p} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Ex. ajustement du seuil de répétition" />}</Field>
                {saved ? <Notice tone="ok">Nouvelle version enregistrée.</Notice> : null}
                <Button type="submit" loading={mutation.isPending} loadingLabel="Enregistrement…">
                  Enregistrer
                </Button>
              </CardBody>
            </Card>
          ) : null}
          <Card>
            <CardHeader title="Historique des versions" />
            <ul className="divide-y divide-line">
              {data.history.map((h) => (
                <li key={h.version} className="px-4 py-2.5 text-[13px]">
                  <p className="font-medium text-ink-900">
                    Version {h.version} — {h.comment}
                  </p>
                  <p className="text-xs text-ink-500">
                    {formatDateTime(h.at)} · {h.by}
                  </p>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </form>
    </>
  );
}
