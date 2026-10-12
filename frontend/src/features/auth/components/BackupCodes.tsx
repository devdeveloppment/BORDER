import { Download } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/feedback";

/**
 * Affichage UNIQUE des codes de secours renvoyés par le backend (après enrôlement, renouvellement ou
 * régénération). Ils ne sont conservés nulle part par l'application : quitter l'écran les efface.
 */
export function BackupCodesPanel({ codes, onDone, doneLabel = "Continuer" }: { codes: string[]; onDone: () => void; doneLabel?: string }) {
  const [saved, setSaved] = useState(false);

  const download = () => {
    const text = `RIZTECH Border Intelligence — codes de secours\nChaque code n'est utilisable qu'une seule fois.\n\n${codes.join("\n")}\n`;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "rbi-codes-de-secours.txt";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <Notice tone="warn" title="Conservez ces codes en lieu sûr">
        Ils ne seront plus jamais affichés. Chacun permet une seule connexion si vous perdez l'accès à votre application d'authentification. Rangez-les
        dans un coffre ou un gestionnaire de mots de passe, jamais avec votre mot de passe.
      </Notice>
      <ul aria-label="Codes de secours" data-testid="backup-codes" className="grid grid-cols-2 gap-2 rounded-[var(--radius-card)] bg-surface-alt p-3 font-mono text-sm text-ink-900">
        {codes.map((code) => (
          <li key={code} className="text-center tracking-wider">
            {code}
          </li>
        ))}
      </ul>
      <Button variant="secondary" className="w-full" onClick={download}>
        <Download aria-hidden="true" /> Télécharger (.txt)
      </Button>
      <label className="flex items-start gap-2 text-[13px] text-ink-700">
        <input type="checkbox" className="mt-0.5 size-4 accent-brand-600" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        J'ai conservé ces codes de secours en lieu sûr.
      </label>
      <Button className="w-full" size="lg" disabled={!saved} onClick={onDone}>
        {doneLabel}
      </Button>
    </div>
  );
}
