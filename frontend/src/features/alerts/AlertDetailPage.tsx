import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, MessageSquarePlus } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { baseAxis, CHART_COLORS, EChart } from "@/components/charts/EChart";
import { AlertStatusBadge, LevelBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { Field, Textarea } from "@/components/ui/form";
import { Dialog, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { ApiError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { AlertDetail, AlertStatus } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { formatDateTime, formatNumber } from "@/lib/format";
import { ACTIVITY_TYPE_LABEL, ALERT_STATUS_LABEL, ALERT_TYPE_LABEL } from "@/lib/labels";
import { PERMISSIONS } from "@/lib/permissions";
import { useMediaQuery } from "@/lib/useMediaQuery";

const TRANSITION_LABEL: Record<AlertStatus, string> = {
  NOUVELLE: "Nouvelle",
  EN_COURS: "Prendre en charge",
  EXAMINEE: "Marquer comme examinée",
  CONFIRMEE: "Confirmer l'écart",
  ECARTEE: "Écarter",
  CLOTUREE: "Clôturer",
};

function FactorBars({ alert }: { alert: AlertDetail }) {
  const total = alert.factors.reduce((s, f) => s + f.points, 0);
  return (
    <div>
      <ul className="space-y-3">
        {alert.factors.map((f) => (
          <li key={f.code}>
            <div className="flex items-baseline justify-between gap-3 text-[13px]">
              <span className="font-medium text-ink-900">{f.label}</span>
              <span className="tabular font-semibold text-navy-900">+{f.points}</span>
            </div>
            <div className="mt-1 h-2 rounded-full bg-surface-alt" role="presentation">
              <div className="h-2 rounded-full bg-brand-600" style={{ width: `${(f.points / f.max_points) * 100}%` }} />
            </div>
            <p className="mt-1 text-xs text-ink-500">
              Observé : {f.observed} · Référence : {f.reference} · barème max {f.max_points} pts
            </p>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-sm">
        <span className="font-semibold text-ink-700">Total (plafonné à 100)</span>
        <span className="tabular text-lg font-semibold text-navy-900">{Math.min(100, total)} / 100</span>
      </div>
    </div>
  );
}

function ComparisonChart({ alert }: { alert: AlertDetail }) {
  const option = useMemo(
    () => ({
      grid: { left: 44, right: 12, top: 28, bottom: 28 },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => formatNumber(v) },
      legend: { top: 0, right: 0, textStyle: { color: CHART_COLORS.text, fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
      xAxis: { type: "category", data: alert.comparison.map((c) => c.label), ...baseAxis, splitLine: { show: false } },
      yAxis: { type: "value", ...baseAxis },
      series: [
        { name: "Observé", type: "bar", data: alert.comparison.map((c) => c.observed), itemStyle: { color: CHART_COLORS.primary, borderRadius: [3, 3, 0, 0] }, barMaxWidth: 22 },
        { name: "Référence", type: "line", data: alert.comparison.map((c) => c.reference), symbol: "circle", symbolSize: 5, lineStyle: { color: CHART_COLORS.navy, type: "dashed" }, itemStyle: { color: CHART_COLORS.navy } },
      ],
    }),
    [alert],
  );
  return <EChart option={option} className="h-56" ariaLabel={`Comparaison de l'activité du ${alert.border_post.name} avec la période de référence`} summary={alert.reference_period} />;
}

function TreatmentPanel({ alert }: { alert: AlertDetail }) {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<AlertStatus | null>(null);
  const [comment, setComment] = useState("");
  const [observation, setObservation] = useState("");

  const mutation = useMutation({
    mutationFn: (payload: Parameters<typeof endpoints.alertAction>[1]) => endpoints.alertAction(alert.id, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(["alert", alert.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["alerts"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setTarget(null);
      setComment("");
      setObservation("");
    },
  });
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;
  const needsReason = target !== null && target !== "EN_COURS";

  if (!can(PERMISSIONS.alertsTake) && !can(PERMISSIONS.alertsComment)) {
    return <Notice>Consultation en lecture seule : votre rôle ne permet pas d'agir sur les alertes.</Notice>;
  }

  return (
    <div className="space-y-4">
      {alert.allowed_transitions.length ? (
        <div className="flex flex-wrap gap-2">
          {alert.allowed_transitions.map((s) => (
            <Button key={s} variant={s === "EN_COURS" ? "primary" : s === "ECARTEE" ? "secondary" : "navy"} onClick={() => (s === "EN_COURS" ? mutation.mutate({ action: "CHANGEMENT_STATUT", to_status: s }) : setTarget(s))} loading={mutation.isPending && target === null && s === "EN_COURS"}>
              {TRANSITION_LABEL[s]}
            </Button>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-ink-500">Aucune transition de statut disponible pour votre rôle à ce stade.</p>
      )}

      {can(PERMISSIONS.alertsComment) ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate({ action: "OBSERVATION", comment: observation });
          }}
          className="space-y-2"
        >
          <Field label="Ajouter une observation">{(p) => <Textarea {...p} value={observation} onChange={(e) => setObservation(e.target.value)} placeholder="Constat, vérification effectuée, élément de contexte…" />}</Field>
          <Button type="submit" variant="secondary" disabled={!observation.trim()} loading={mutation.isPending && target === null}>
            <MessageSquarePlus aria-hidden="true" /> Enregistrer l'observation
          </Button>
        </form>
      ) : null}

      {apiError && !target ? <Notice tone="warn">{apiError.problem?.title ?? "L'action n'a pas abouti."}</Notice> : null}

      <Dialog
        open={target !== null}
        onOpenChange={(o) => !o && setTarget(null)}
        title={target ? TRANSITION_LABEL[target] : ""}
        description={target ? `Nouveau statut : ${ALERT_STATUS_LABEL[target]}. Cette action est tracée dans l'historique et le journal d'audit.` : undefined}
        footer={
          <>
            <Button variant="secondary" onClick={() => setTarget(null)}>
              Annuler
            </Button>
            <Button onClick={() => target && mutation.mutate({ action: "CHANGEMENT_STATUT", to_status: target, comment })} disabled={needsReason && !comment.trim()} loading={mutation.isPending} loadingLabel="Enregistrement…">
              Valider
            </Button>
          </>
        }
      >
        <Field label="Motif" required={needsReason} error={apiError?.problem?.errors?.comment?.[0] ?? null} hint={target === "CONFIRMEE" ? "« Confirmée » signifie : écart vérifié par un humain — jamais une qualification juridique." : undefined}>
          {(p) => <Textarea {...p} value={comment} onChange={(e) => setComment(e.target.value)} />}
        </Field>
      </Dialog>
    </div>
  );
}

function History({ alert }: { alert: AlertDetail }) {
  return (
    <ol className="space-y-4 border-l-2 border-line pl-4">
      {alert.actions.map((a) => (
        <li key={a.id} className="relative">
          <span className={cn("absolute top-1.5 -left-[21px] size-2.5 rounded-full", a.action === "OBSERVATION" ? "bg-ink-500" : "bg-brand-600")} aria-hidden="true" />
          <p className="text-[13px] font-medium text-ink-900">
            {a.action === "OBSERVATION" ? "Observation" : a.action === "CREATION" ? "Création" : `${a.from_status ? ALERT_STATUS_LABEL[a.from_status] : ""} → ${a.to_status ? ALERT_STATUS_LABEL[a.to_status] : ""}`}
          </p>
          <p className="text-xs text-ink-500">
            {formatDateTime(a.at)} · {a.actor}
          </p>
          {a.comment ? <p className="mt-1 text-[13px] text-ink-700">{a.comment}</p> : null}
        </li>
      ))}
    </ol>
  );
}

/** Écran 14 — Détail d'une alerte : explication, décomposition du score, traitement humain. */
export function AlertDetailPage() {
  const { id = "" } = useParams();
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const { data: alert, isLoading, error, refetch } = useQuery({ queryKey: ["alert", id], queryFn: () => endpoints.alert(id) });

  if (error) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (isLoading || !alert) return <LoadingBlock rows={10} />;

  const explanation = (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Pourquoi cette alerte ?" />
        <CardBody>
          <p className="text-[15px] leading-relaxed text-ink-900">{alert.explanation}</p>
          <p className="mt-3 flex items-start gap-1.5 rounded-md bg-brand-50 px-3 py-2 text-xs font-medium text-navy-900">
            <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
            {alert.disclaimer}
          </p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Décomposition de l'indicateur" description={`Modèle de pondération ${alert.model_version}`} />
        <CardBody>
          <FactorBars alert={alert} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Comparaison avec la période de référence" description={alert.reference_period} />
        <CardBody>
          <ComparisonChart alert={alert} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Activités liées" />
        <ul className="divide-y divide-line">
          {alert.linked_activities.map((a) => (
            <li key={a.id}>
              <Link to={`/app/activites/${a.id}`} className="flex items-center justify-between gap-3 px-4 py-2.5 text-[13px] hover:bg-brand-50">
                <span className="font-medium text-brand-700">{a.reference}</span>
                <span className="text-ink-500">
                  {ACTIVITY_TYPE_LABEL[a.activity_type]} · {formatDateTime(a.occurred_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );

  const treatment = (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Informations" />
        <CardBody>
          <DefinitionList
            items={[
              { label: "Type", value: ALERT_TYPE_LABEL[alert.alert_type] },
              { label: "Poste", value: <Link className="text-brand-700 hover:underline" to={`/app/postes/${alert.border_post.id}`}>{alert.border_post.name}</Link> },
              { label: "Détectée le", value: formatDateTime(alert.detected_at) },
              { label: "Responsable", value: alert.assignee?.name ?? "Non assignée" },
            ]}
          />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Traitement" description="La décision appartient toujours à une personne habilitée." />
        <CardBody>
          <TreatmentPanel alert={alert} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Historique des actions" />
        <CardBody>
          <History alert={alert} />
        </CardBody>
      </Card>
    </div>
  );

  return (
    <>
      <PageHeader
        breadcrumb={{ label: "Alertes", to: "/app/alertes" }}
        title={alert.title}
        description={alert.reference}
        actions={
          <>
            <LevelBadge level={alert.level} score={alert.score} className="text-sm" />
            <AlertStatusBadge status={alert.status} />
          </>
        }
      />
      {isDesktop ? (
        <div className="grid grid-cols-[1.4fr_1fr] gap-5">
          {explanation}
          {treatment}
        </div>
      ) : (
        <Tabs defaultValue="explication">
          <TabsList aria-label="Sections de l'alerte">
            <TabsTrigger value="explication">Explication</TabsTrigger>
            <TabsTrigger value="traitement">Traitement</TabsTrigger>
          </TabsList>
          <TabsContent value="explication" className="pt-4">
            {explanation}
          </TabsContent>
          <TabsContent value="traitement" className="pt-4">
            {treatment}
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}
