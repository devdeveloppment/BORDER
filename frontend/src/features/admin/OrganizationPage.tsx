import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { endpoints } from "@/lib/api/endpoints";
import { formatDate } from "@/lib/format";
import { ORG_STATUS_LABEL } from "@/lib/labels";

/** Fiche de l'organisme courant : identité, statut et autorisation formelle (§9.16). */
export function OrganizationPage() {
  const { data: org, isLoading, error, refetch } = useQuery({ queryKey: ["organization"], queryFn: endpoints.organization });

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
      <PageHeader title={org.name} description="Espace organisationnel isolé" actions={<Badge tone={org.status === "ACTIVE" ? "ok" : "warn"}>{ORG_STATUS_LABEL[org.status]}</Badge>} />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="Identité" />
          <CardBody>
            <DefinitionList
              items={[
                { label: "Raison sociale", value: org.name },
                { label: "Sigle", value: org.short_name },
                { label: "Nature", value: org.type },
                { label: "Fuseau horaire", value: org.timezone },
                { label: "Mode d'hébergement", value: org.deployment_mode === "mutualise" ? "Mutualisé (isolation logique + RLS)" : "Dédié" },
                { label: "Utilisateurs", value: org.users_count },
              ]}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Autorisation d'accès" description="Accordée par l'opérateur de la plateforme" />
          <CardBody className="space-y-4">
            <DefinitionList
              items={[
                { label: "Référence de convention", value: org.authorization_reference ?? "—" },
                { label: "Valide du", value: org.valid_from ? formatDate(org.valid_from) : "—" },
                { label: "Valide jusqu'au", value: org.valid_until ? formatDate(org.valid_until) : "Sans échéance" },
              ]}
            />
            <Notice>Aucun partage de données avec un autre organisme n'est actif. Toute évolution nécessite une convention formelle.</Notice>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
