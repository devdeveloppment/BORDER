import { QRCodeSVG } from "qrcode.react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/form";
import type { TotpEnrollment } from "@/lib/api/types";

/**
 * Enrôlement TOTP (écran 7, P2.10). Le secret et l'URI ne vivent que dans l'état de ce composant : jamais dans
 * l'URL, le stockage du navigateur, les journaux ni un message d'erreur. Le QR code est dessiné localement (SVG),
 * sans aucun appel réseau.
 */
export function TotpEnrollmentPanel({
  enrollment,
  pending,
  error,
  onSubmit,
}: {
  enrollment: TotpEnrollment;
  pending: boolean;
  error: string | null;
  onSubmit: (code: string) => void;
}) {
  const [code, setCode] = useState("");
  const [showKey, setShowKey] = useState(false);
  const groupedKey = enrollment.secret.replace(/(.{4})/g, "$1 ").trim();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit(code);
  };

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <ol className="list-decimal space-y-1 pl-5 text-[13px] text-ink-700">
        <li>Ouvrez votre application d'authentification (TOTP).</li>
        <li>Scannez le QR code ou saisissez la clé manuellement.</li>
        <li>Saisissez le code à 6 chiffres affiché pour confirmer.</li>
      </ol>
      <div className="flex justify-center">
        <div className="rounded-[var(--radius-card)] border border-line bg-white p-3">
          <QRCodeSVG value={enrollment.otpauth_uri} size={176} level="M" title="QR code d'enrôlement de l'application d'authentification" />
        </div>
      </div>
      <div className="text-center">
        <button type="button" className="text-[13px] font-medium text-brand-700 hover:underline" aria-expanded={showKey} onClick={() => setShowKey((v) => !v)}>
          {showKey ? "Masquer la clé de saisie manuelle" : "Afficher la clé de saisie manuelle"}
        </button>
        {showKey ? (
          <p className="mt-2 rounded-md bg-surface-alt px-3 py-2 font-mono text-sm tracking-wider break-all text-ink-900 select-all" data-testid="totp-secret" aria-label="Clé de saisie manuelle">
            {groupedKey}
          </p>
        ) : null}
      </div>
      {error ? <Notice tone="warn">{error}</Notice> : null}
      <Field label="Code de vérification" required>
        {(p) => (
          <Input
            {...p}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoComplete="one-time-code"
            className="h-12 text-center text-lg tracking-[0.4em] tabular"
            maxLength={6}
          />
        )}
      </Field>
      <Button type="submit" className="w-full" size="lg" loading={pending} loadingLabel="Vérification…" disabled={code.length !== 6}>
        Confirmer l'enrôlement
      </Button>
    </form>
  );
}
