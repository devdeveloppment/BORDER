import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/form";
import { ApiError, describeError } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";

const EMPTY = { organization: "", role: "", name: "", email: "", phone: "", request_type: "demonstration", message: "", consent: "false" };

/** Écran 5 — Demande de démonstration ou d'accès. Aucune création de compte automatique. */
export function ContactPage() {
  const [form, setForm] = useState(EMPTY);
  const mutation = useMutation({ mutationFn: endpoints.submitAccessRequest });
  const errors = mutation.error instanceof ApiError ? (mutation.error.problem?.errors ?? {}) : {};
  const err = (k: string) => errors[k]?.[0] ?? null;
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    mutation.mutate(form);
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="text-2xl font-semibold text-navy-900">Demander une démonstration ou un accès</h1>
      <p className="mt-2 text-ink-500">
        Toute demande est examinée par l'opérateur de la plateforme. Aucun compte n'est créé automatiquement : l'accès d'un organisme nécessite une autorisation préalable formalisée.
      </p>

      {mutation.isSuccess ? (
        <Notice tone="ok" title="Demande envoyée" className="mt-8">
          Votre demande a bien été enregistrée. Vous serez recontacté par l'équipe RIZTECH.
        </Notice>
      ) : (
        <form onSubmit={onSubmit} noValidate className="mt-8 grid gap-4 sm:grid-cols-2">
          <Field label="Organisme" required error={err("organization")}>
            {(p) => <Input {...p} autoComplete="organization" value={form.organization} onChange={set("organization")} />}
          </Field>
          <Field label="Fonction" required error={err("role")}>
            {(p) => <Input {...p} autoComplete="organization-title" value={form.role} onChange={set("role")} />}
          </Field>
          <Field label="Nom et prénom" required error={err("name")}>
            {(p) => <Input {...p} autoComplete="name" value={form.name} onChange={set("name")} />}
          </Field>
          <Field label="Email professionnel" required error={err("email")}>
            {(p) => <Input {...p} type="email" autoComplete="email" value={form.email} onChange={set("email")} />}
          </Field>
          <Field label="Téléphone" hint="Facultatif">
            {(p) => <Input {...p} type="tel" autoComplete="tel" value={form.phone} onChange={set("phone")} />}
          </Field>
          <Field label="Type de demande" required error={err("request_type")}>
            {(p) => (
              <Select {...p} value={form.request_type} onChange={set("request_type")}>
                <option value="demonstration">Démonstration</option>
                <option value="acces">Accès pour un organisme</option>
              </Select>
            )}
          </Field>
          <Field label="Message" className="sm:col-span-2">
            {(p) => <Textarea {...p} value={form.message} onChange={set("message")} />}
          </Field>
          <div className="sm:col-span-2">
            <label className="flex items-start gap-2 text-[13px] text-ink-700">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-brand-600"
                checked={form.consent === "true"}
                onChange={(e) => setForm((f) => ({ ...f, consent: String(e.target.checked) }))}
                aria-invalid={err("consent") ? true : undefined}
                aria-describedby={err("consent") ? "consent-error" : undefined}
              />
              J'accepte que ces informations soient utilisées pour traiter ma demande.
            </label>
            {err("consent") ? (
              <p id="consent-error" role="alert" className="mt-1 text-xs font-medium text-danger-ink">
                {err("consent")}
              </p>
            ) : null}
          </div>
          {mutation.isError && !Object.keys(errors).length ? (
            <Notice tone="warn" className="sm:col-span-2">
              {describeError(mutation.error)}
            </Notice>
          ) : null}
          <div className="sm:col-span-2">
            <Button type="submit" size="lg" loading={mutation.isPending} loadingLabel="Envoi…" className="w-full sm:w-auto">
              Envoyer la demande
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
