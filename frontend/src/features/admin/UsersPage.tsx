import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock, Notice } from "@/components/ui/feedback";
import { Field, Input, Select } from "@/components/ui/form";
import { Dialog } from "@/components/ui/overlay";
import { DefinitionList, PageHeader } from "@/components/ui/page";
import { DataTable } from "@/components/ui/table";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { OrgUser, RoleCode } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { formatDateTime } from "@/lib/format";
import { ROLE_LABEL } from "@/lib/labels";
import { PERMISSIONS } from "@/lib/permissions";

const ORG_ROLES: RoleCode[] = ["ORG_ADMIN", "SUPERVISOR", "AGENT", "ANALYST", "AUDITOR"];
const USERS_KEY = ["users"] as const;

const fullName = (u: Pick<OrgUser, "first_name" | "last_name" | "email">) => `${u.first_name} ${u.last_name}`.trim() || u.email;

/**
 * Écran 23 — Comptes de l'organisme (P2.10 : API réelle). Lecture : `users.view` ; actions : `users.manage`.
 * Les règles (pas d'auto-administration, dernier Administrateur institutionnel, rôles d'organisme seulement)
 * sont appliquées par le backend ; l'écran affiche ses refus tels quels.
 */
export function UsersPage() {
  const { can } = useSession();
  const manage = can(PERMISSIONS.usersManage);
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data, isLoading, error, refetch } = useQuery({ queryKey: USERS_KEY, queryFn: endpoints.users });
  const rows = (data ?? []).filter((u) => (!role || u.roles.includes(role as RoleCode)) && (!status || String(u.is_active) === status));
  const selected = data?.find((u) => u.id === selectedId) ?? null;

  return (
    <>
      <PageHeader
        title="Utilisateurs"
        description="Comptes de votre organisme uniquement. MFA obligatoire pour les rôles sensibles."
        actions={
          manage ? (
            <Button onClick={() => setCreating(true)}>
              <UserPlus aria-hidden="true" /> Créer un compte
            </Button>
          ) : null
        }
      />
      <Card>
        <div className="flex flex-wrap gap-3 border-b border-line p-4">
          <Select aria-label="Rôle" value={role} onChange={(e) => setRole(e.target.value)} className="w-60">
            <option value="">Tous les rôles</option>
            {ORG_ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r]}
              </option>
            ))}
          </Select>
          <Select aria-label="Statut du compte" value={status} onChange={(e) => setStatus(e.target.value)} className="w-44">
            <option value="">Tous statuts</option>
            <option value="true">Actifs</option>
            <option value="false">Désactivés</option>
          </Select>
        </div>
        {error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading ? (
          <LoadingBlock className="p-4" rows={8} />
        ) : rows.length === 0 ? (
          <EmptyState title="Aucun utilisateur" />
        ) : (
          <DataTable<OrgUser>
            caption="Utilisateurs de l'organisme"
            rows={rows}
            rowKey={(u) => u.id}
            onRowClick={(u) => setSelectedId(u.id)}
            columns={[
              { key: "name", header: "Nom", cell: (u) => <span className="font-medium text-ink-900">{fullName(u)}</span> },
              { key: "email", header: "Email", cell: (u) => u.email },
              { key: "roles", header: "Rôle(s)", cell: (u) => (u.roles.length ? u.roles.map((r) => ROLE_LABEL[r]).join(", ") : <span className="text-ink-500">Aucun</span>) },
              { key: "mfa", header: "MFA", cell: (u) => <Badge tone={u.mfa_enabled ? "ok" : "neutral"}>{u.mfa_enabled ? "Activée" : "Non activée"}</Badge> },
              { key: "status", header: "Statut", cell: (u) => <Badge tone={u.is_active ? "brand" : "neutral"}>{u.is_active ? "Actif" : "Désactivé"}</Badge> },
              { key: "last", header: "Dernier accès", cell: (u) => (u.last_login ? formatDateTime(u.last_login) : "Jamais") },
            ]}
            mobileCard={(u) => (
              <button type="button" onClick={() => setSelectedId(u.id)} className="block w-full px-4 py-3 text-left">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[13px] font-medium text-ink-900">{fullName(u)}</p>
                  <Badge tone={u.is_active ? "brand" : "neutral"}>{u.is_active ? "Actif" : "Désactivé"}</Badge>
                </div>
                <p className="mt-0.5 text-xs text-ink-500">
                  {u.email} · {u.roles.map((r) => ROLE_LABEL[r]).join(", ")}
                </p>
              </button>
            )}
          />
        )}
      </Card>
      {manage ? <CreateUserDialog open={creating} onClose={() => setCreating(false)} /> : null}
      <UserDialog user={selected} manage={manage} onClose={() => setSelectedId(null)} />
    </>
  );
}

function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "" });
  const [roles, setRoles] = useState<RoleCode[]>([]);
  const catalog = useQuery({ queryKey: ["roles"], queryFn: endpoints.roles, enabled: open });
  const mutation = useMutation({
    mutationFn: () => endpoints.createUser({ ...form, roles }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: USERS_KEY });
      setForm({ email: "", first_name: "", last_name: "" });
      setRoles([]);
      onClose();
    },
  });
  const apiError = mutation.error instanceof ApiError ? mutation.error : null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate();
  };
  const toggle = (code: RoleCode) => setRoles((rs) => (rs.includes(code) ? rs.filter((r) => r !== code) : [...rs, code]));

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Créer un compte"
      description="Le compte est créé sans mot de passe : l'utilisateur le définit par « Mot de passe oublié » (lien à usage unique)."
    >
      <form id="create-user" onSubmit={submit} className="space-y-4" noValidate>
        {mutation.isError && !apiError?.problem?.errors ? <Notice tone="warn">{describeError(mutation.error)}</Notice> : null}
        <Field label="Adresse email professionnelle" required error={apiError?.fieldError("email")}>
          {(p) => <Input {...p} type="email" autoComplete="off" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Prénom" error={apiError?.fieldError("first_name")}>
            {(p) => <Input {...p} value={form.first_name} onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))} />}
          </Field>
          <Field label="Nom" error={apiError?.fieldError("last_name")}>
            {(p) => <Input {...p} value={form.last_name} onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))} />}
          </Field>
        </div>
        <fieldset>
          <legend className="text-[13px] font-medium text-ink-700">Rôles</legend>
          {catalog.isError ? <Notice tone="warn">{describeError(catalog.error)}</Notice> : null}
          <ul className="mt-2 space-y-1.5">
            {(catalog.data ?? []).map((r) => (
              <li key={r.code}>
                <label className="flex items-center gap-2 text-[13px] text-ink-700">
                  <input type="checkbox" className="size-4 accent-brand-600" checked={roles.includes(r.code)} onChange={() => toggle(r.code)} />
                  {r.name}
                  {r.mfa_required ? <Badge>MFA obligatoire</Badge> : null}
                </label>
              </li>
            ))}
          </ul>
          {apiError?.fieldError("roles") ? <p className="mt-1 text-xs font-medium text-danger-ink">{apiError.fieldError("roles")}</p> : null}
        </fieldset>
      </form>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Annuler
        </Button>
        <Button type="submit" form="create-user" loading={mutation.isPending} loadingLabel="Création…" disabled={!form.email}>
          Créer le compte
        </Button>
      </div>
    </Dialog>
  );
}

function UserDialog({ user, manage, onClose }: { user: OrgUser | null; manage: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { user: me } = useSession();
  const [newRole, setNewRole] = useState<RoleCode | "">("");
  const [confirmReset, setConfirmReset] = useState(false);
  const refreshUsers = () => queryClient.invalidateQueries({ queryKey: USERS_KEY });
  const action = useMutation({
    mutationFn: async (run: () => Promise<unknown>) => run(),
    onSuccess: async () => {
      setNewRole("");
      setConfirmReset(false);
      await refreshUsers();
    },
  });
  const self = !!user && user.id === me?.id;
  const available = ORG_ROLES.filter((r) => !user?.roles.includes(r));
  const close = () => {
    action.reset();
    setConfirmReset(false);
    onClose();
  };

  return (
    <Dialog open={!!user} onOpenChange={(o) => !o && close()} title={user ? fullName(user) : "Compte"} side="right">
      {user ? (
        <div className="space-y-5">
          <DefinitionList
            items={[
              { label: "Email", value: user.email },
              { label: "Statut", value: <Badge tone={user.is_active ? "brand" : "neutral"}>{user.is_active ? "Actif" : "Désactivé"}</Badge> },
              { label: "MFA", value: user.mfa_enabled ? "Activée" : "Non activée" },
              { label: "Dernier accès", value: user.last_login ? formatDateTime(user.last_login) : "Jamais" },
            ]}
          />
          {action.isError ? <Notice tone="warn">{describeError(action.error)}</Notice> : null}
          {action.isSuccess ? <Notice tone="ok">Modification enregistrée.</Notice> : null}

          <section aria-labelledby="roles-title">
            <h3 id="roles-title" className="text-[13px] font-semibold text-ink-900">
              Rôles
            </h3>
            <ul className="mt-2 flex flex-wrap gap-2">
              {user.roles.length === 0 ? <li className="text-[13px] text-ink-500">Aucun rôle</li> : null}
              {user.roles.map((r) => (
                <li key={r}>
                  <Badge tone="brand">
                    {ROLE_LABEL[r]}
                    {manage && !self ? (
                      <button type="button" className="ml-1 rounded hover:bg-brand-100" aria-label={`Retirer le rôle ${ROLE_LABEL[r]}`} onClick={() => action.mutate(() => endpoints.revokeRole(user.id, r))}>
                        <X className="size-3" aria-hidden="true" />
                      </button>
                    ) : null}
                  </Badge>
                </li>
              ))}
            </ul>
            {manage && !self && available.length ? (
              <div className="mt-3 flex gap-2">
                <Select aria-label="Rôle à attribuer" value={newRole} onChange={(e) => setNewRole(e.target.value as RoleCode | "")} className="flex-1">
                  <option value="">Attribuer un rôle…</option>
                  {available.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </Select>
                <Button variant="secondary" disabled={!newRole} loading={action.isPending} onClick={() => newRole && action.mutate(() => endpoints.assignRole(user.id, newRole))}>
                  Attribuer
                </Button>
              </div>
            ) : null}
          </section>

          {manage && self ? <Notice>Vous ne pouvez pas modifier votre propre compte : un autre administrateur doit le faire.</Notice> : null}
          {manage && !self ? (
            <section aria-labelledby="account-actions" className="space-y-2">
              <h3 id="account-actions" className="text-[13px] font-semibold text-ink-900">
                Compte
              </h3>
              <div className="flex flex-wrap gap-2">
                <Button variant={user.is_active ? "danger" : "primary"} loading={action.isPending} onClick={() => action.mutate(() => endpoints.setUserActive(user.id, !user.is_active))}>
                  {user.is_active ? "Désactiver le compte" : "Réactiver le compte"}
                </Button>
                {confirmReset ? (
                  <Button variant="danger" loading={action.isPending} onClick={() => action.mutate(() => endpoints.resetUserMfa(user.id))}>
                    Confirmer la réinitialisation MFA
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => setConfirmReset(true)}>
                    Réinitialiser la MFA
                  </Button>
                )}
              </div>
              <p className="text-xs text-ink-500">La désactivation et la réinitialisation MFA ferment immédiatement toutes les sessions du compte.</p>
            </section>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  );
}
