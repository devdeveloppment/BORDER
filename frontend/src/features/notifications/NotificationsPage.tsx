import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page";
import { endpoints } from "@/lib/api/endpoints";
import type { Notification } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

const PRIORITY: Record<Notification["priority"], { label: string; tone: "brand" | "warn" | "danger" }> = {
  info: { label: "Information", tone: "brand" },
  attention: { label: "Attention", tone: "warn" },
  urgent: { label: "Urgent", tone: "danger" },
};

/** Écran 21 — Centre de notifications. */
export function NotificationsPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [priority, setPriority] = useState("");
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["notifications"], queryFn: endpoints.notifications });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const markOne = useMutation({ mutationFn: endpoints.markNotificationRead, onSuccess: invalidate });
  const markAll = useMutation({ mutationFn: endpoints.markAllNotificationsRead, onSuccess: invalidate });

  const rows = (data ?? []).filter((n) => (filter === "all" || !n.read_at) && (!priority || n.priority === priority));
  const unread = data?.filter((n) => !n.read_at).length ?? 0;

  return (
    <>
      <PageHeader
        title="Notifications"
        description={`${unread} non lue(s)`}
        actions={
          <Button variant="secondary" onClick={() => markAll.mutate()} disabled={!unread} loading={markAll.isPending}>
            <CheckCheck aria-hidden="true" /> Tout marquer comme lu
          </Button>
        }
      />
      <Card>
        <div className="flex flex-wrap gap-3 border-b border-line p-4">
          <Select aria-label="Statut de lecture" value={filter} onChange={(e) => setFilter(e.target.value as "all" | "unread")} className="w-44">
            <option value="all">Toutes</option>
            <option value="unread">Non lues</option>
          </Select>
          <Select aria-label="Priorité" value={priority} onChange={(e) => setPriority(e.target.value)} className="w-44">
            <option value="">Toutes priorités</option>
            <option value="info">Information</option>
            <option value="attention">Attention</option>
            <option value="urgent">Urgent</option>
          </Select>
        </div>
        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading ? (
          <LoadingBlock className="p-4" />
        ) : rows.length === 0 ? (
          <EmptyState positive title="Vous êtes à jour" />
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((n) => (
              <li key={n.id} className={cn("flex flex-wrap items-start gap-3 px-4 py-3", !n.read_at && "bg-brand-50/60")}>
                <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-brand-600")} aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-ink-900">
                    {n.title} <Badge tone={PRIORITY[n.priority].tone}>{PRIORITY[n.priority].label}</Badge>
                    {!n.read_at ? <span className="sr-only">(non lue)</span> : null}
                  </p>
                  <p className="mt-0.5 text-[13px] text-ink-700">{n.body}</p>
                  <p className="mt-0.5 text-xs text-ink-500">{formatDateTime(n.created_at)}</p>
                </div>
                <div className="flex gap-2">
                  {n.target?.type === "alert" ? (
                    <Link to={`/app/alertes/${n.target.id}`} onClick={() => !n.read_at && markOne.mutate(n.id)} className="rounded-md px-2 py-1 text-[13px] font-medium text-brand-700 hover:bg-brand-50">
                      Ouvrir
                    </Link>
                  ) : null}
                  {!n.read_at ? (
                    <Button variant="ghost" size="sm" onClick={() => markOne.mutate(n.id)}>
                      Marquer comme lue
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
