import { createHmac } from "node:crypto";
import { expect, type Browser, type BrowserContext, type Page } from "@playwright/test";

/** Environnement fourni par scripts/e2e.py (aucune valeur par défaut : jamais l'environnement de développement). */
export function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} absent : lancer les tests par « py scripts/e2e.py ».`);
  return value;
}

// --- TOTP (RFC 6238, paramètres django-otp : SHA-1, 6 chiffres, pas de 30 s) -----------------------------

function base32(secret: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0;
  let value = 0;
  const out: number[] = [];
  for (const char of secret.replace(/[\s=]/g, "").toUpperCase()) {
    const index = alphabet.indexOf(char);
    if (index < 0) throw new Error("clé TOTP illisible");
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 255);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

function totpAt(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const hmac = createHmac("sha1", base32(secret)).update(counter).digest();
  const offset = hmac[hmac.length - 1]! & 15;
  return String((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

const lastStep = new Map<string, number>();

/** Code TOTP d'un pas jamais utilisé pour ce secret : le backend refuse le rejeu d'un code (django-otp). */
export async function freshTotp(secret: string): Promise<string> {
  let step = Math.floor(Date.now() / 30_000);
  const previous = lastStep.get(secret);
  if (previous !== undefined && step <= previous) {
    await new Promise((resolve) => setTimeout(resolve, (previous + 1) * 30_000 - Date.now() + 500));
    step = Math.floor(Date.now() / 30_000);
  }
  lastStep.set(secret, step);
  return totpAt(secret, step);
}

// --- Mailpit (capture des e-mails de l'environnement E2E) ---------------------------------------------------

interface MailpitSearch {
  messages: { ID: string }[];
}

/** Lien de réinitialisation reçu par `email` (envoyé par le worker Celery) : chemin relatif à l'application. */
export async function resetLink(email: string): Promise<string> {
  const api = env("RBI_E2E_MAILPIT_URL");
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    const search = (await (await fetch(`${api}/api/v1/search?query=${encodeURIComponent(`to:"${email}"`)}`)).json()) as MailpitSearch;
    const id = search.messages[0]?.ID;
    if (id) {
      const message = (await (await fetch(`${api}/api/v1/message/${id}`)).json()) as { Text: string };
      const match = /\/connexion\/recuperation\?token=[^\s]+/.exec(message.Text);
      if (match) return match[0];
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`aucun lien de réinitialisation reçu pour ${email}`);
}

// --- Navigateur instrumenté -----------------------------------------------------------------------------------

export interface Actor {
  context: BrowserContext;
  page: Page;
  /** Violations CSP et erreurs JavaScript observées (doivent rester vides). */
  problems: string[];
  /** Réponses /api/v1 servies par MSW (en-tête X-RBI-Mock) : modules reportés uniquement. */
  mocked: string[];
  /** Réponses /api/v1 de l'API réelle. */
  real: string[];
  secret?: string;
}

export async function newActor(browser: Browser): Promise<Actor> {
  const context = await browser.newContext({ acceptDownloads: true });
  await context.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      const list = ((window as unknown as { __cspViolations?: string[] }).__cspViolations ??= []);
      list.push(`${e.violatedDirective} ${e.blockedURI}`);
    });
  });
  const page = await context.newPage();
  const actor: Actor = { context, page, problems: [], mocked: [], real: [] };
  page.on("pageerror", (error) => actor.problems.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (/Content Security Policy/i.test(message.text())) actor.problems.push(`csp: ${message.text()}`);
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/v1/")) return;
    const entry = `${response.request().method()} ${url.pathname}`;
    (response.headers()["x-rbi-mock"] === "true" ? actor.mocked : actor.real).push(entry);
  });
  return actor;
}

export async function cspViolations(actor: Actor): Promise<string[]> {
  const fromPage = await actor.page.evaluate(() => (window as unknown as { __cspViolations?: string[] }).__cspViolations ?? []);
  return [...actor.problems, ...fromPage];
}

/** Requête de l'API depuis la page (cookies de session, même origine) : statut et corps. */
export async function pageFetch(page: Page, path: string, init: { method?: string; body?: unknown } = {}): Promise<{ status: number; body: unknown }> {
  return page.evaluate(
    async ({ path, init }) => {
      const csrf = /(?:^|; )csrftoken=([^;]*)/.exec(document.cookie)?.[1];
      const response = await fetch(`/api/v1${path}`, {
        method: init.method ?? "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json", "Content-Type": "application/json", ...(csrf ? { "X-CSRFToken": decodeURIComponent(csrf) } : {}) },
        body: init.body === undefined ? undefined : JSON.stringify(init.body),
      });
      const text = await response.text();
      let body: unknown = text;
      try {
        body = JSON.parse(text);
      } catch {
        /* corps non JSON */
      }
      return { status: response.status, body };
    },
    { path, init },
  );
}

// --- Parcours d'authentification réels ----------------------------------------------------------------------

/** Mot de passe puis, selon l'étape exigée par le backend, enrôlement TOTP (secret lu à l'écran) ou code TOTP. */
export async function signIn(actor: Actor, email: string, password: string): Promise<void> {
  const { page } = actor;
  await page.goto("/connexion");
  await page.getByLabel(/^Adresse email/).fill(email);
  await page.getByLabel(/^Mot de passe/).fill(password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await page.waitForURL(/\/(app|connexion\/mfa)/);
  if (!page.url().includes("/connexion/mfa")) return;

  if (await page.getByRole("button", { name: "Commencer l'enrôlement" }).isVisible()) {
    await page.getByRole("button", { name: "Commencer l'enrôlement" }).click();
    await expect(page.getByRole("img", { name: "QR code d'enrôlement de l'application d'authentification" })).toBeVisible();
    await page.getByRole("button", { name: "Afficher la clé de saisie manuelle" }).click();
    actor.secret = ((await page.getByTestId("totp-secret").textContent()) ?? "").replace(/\s/g, "");
    expect(actor.secret).toMatch(/^[A-Z2-7]{16,}$/);
    await page.getByLabel(/^Code de vérification/).fill(await freshTotp(actor.secret));
    await page.getByRole("button", { name: "Confirmer l'enrôlement" }).click();
    // Codes de secours : affichés une seule fois, continuer exige d'en confirmer la conservation.
    await expect(page.getByTestId("backup-codes").getByRole("listitem")).toHaveCount(10);
    await expect(page.getByRole("button", { name: "Accéder à l'application" })).toBeDisabled();
    await page.getByLabel("J'ai conservé ces codes de secours en lieu sûr.").check();
    await page.getByRole("button", { name: "Accéder à l'application" }).click();
  } else {
    if (!actor.secret) throw new Error(`secret TOTP inconnu pour ${email}`);
    await page.getByLabel(/^Code de vérification/).fill(await freshTotp(actor.secret));
    await page.getByRole("button", { name: "Vérifier" }).click();
  }
  await page.waitForURL(/\/app/);
}

/** Invitation : « mot de passe oublié » → lien reçu dans Mailpit → nouveau mot de passe. */
export async function acceptInvitation(actor: Actor, email: string, password: string): Promise<void> {
  const { page } = actor;
  await page.goto("/connexion/recuperation");
  await page.getByLabel(/^Adresse email/).fill(email);
  await page.getByRole("button", { name: "Envoyer le lien" }).click();
  await expect(page.getByText("Demande prise en compte")).toBeVisible();
  await page.goto(await resetLink(email));
  await expect(page).toHaveURL(/\/connexion\/recuperation$/); // jeton retiré de l'URL
  await page.getByLabel(/^Nouveau mot de passe/).fill(password);
  await page.getByLabel(/^Confirmer le mot de passe/).fill(password);
  await page.getByRole("button", { name: "Définir le mot de passe" }).click();
  await expect(page.getByText("Mot de passe mis à jour")).toBeVisible();
}
