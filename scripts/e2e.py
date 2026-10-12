"""Tests E2E de la pile intégrée dans un environnement Docker JETABLE (P2.10, ADR 0012).

    py scripts/e2e.py            # environnement créé, tests HTTP puis TLS, environnement détruit
    py scripts/e2e.py --keep     # conserve l'environnement à la fin (inspection)

Garanties :
- projet Docker « rbi-e2e » : volumes, réseaux et ports propres (127.0.0.1:18080, 18443, 18025), sous-réseau
  distinct ; l'environnement de développement (projet « rbi ») n'est jamais visé ;
- secrets générés pour l'exécution dans un répertoire temporaire hors du dépôt ; aucun fichier versionné modifié ;
- avant toute suppression, preuve que chaque volume visé porte l'étiquette du projet E2E et son préfixe, et
  qu'aucun volume de développement n'est concerné ; après, vérification que ceux du développement sont intacts ;
- certificat TLS autosigné généré pour l'exécution (openssl de l'image PostgreSQL locale), jamais versionné.

Bibliothèque standard uniquement (Python 3.10+).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "rbi-e2e"
DEV_PROJECT = "rbi"
HTTP_PORT, HTTPS_PORT, MAILPIT_PORT = 18080, 18443, 18025
EDGE = {"RBI_EDGE_SUBNET": "172.29.90.0/28", "RBI_EDGE_PROXY_IP": "172.29.90.2", "RBI_EDGE_DYNAMIC_RANGE": "172.29.90.8/29"}
SUPER_ADMIN = "superadmin@plateforme.rbi.test"
NODE_IMAGE = "node:24.19.0-alpine"
OPENSSL_IMAGE = "rbi-postgres:16-postgis3.6"  # image locale (Debian) : openssl sans téléchargement

RESULTS: list[tuple[str, bool, str]] = []


def log(message: str) -> None:
    print(f"[e2e] {message}", flush=True)


def run(args: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None, cwd: Path = ROOT,
        check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, input=input_text, text=True, check=check,
                          capture_output=capture, encoding="utf-8", errors="replace")


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    log(f"{'OK ' if ok else 'ÉCHEC'} {name}{' — ' + detail if detail else ''}")


# --- Garde-fous des volumes -----------------------------------------------------------------------------------


def volumes(project: str) -> list[str]:
    out = run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"], capture=True)
    return sorted(v for v in out.stdout.split() if v)


def volume_identity(names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    out = run(["docker", "volume", "inspect", "-f", "{{.Name}} {{.CreatedAt}}", *names], capture=True)
    return dict(line.split(" ", 1) for line in out.stdout.strip().splitlines())


def safe_teardown(compose: list[str], env: dict[str, str]) -> None:
    """Supprime l'environnement E2E et SES volumes, après preuve qu'aucun volume de développement n'est visé."""
    assert PROJECT != DEV_PROJECT
    targets = volumes(PROJECT)
    protected = set(volumes(DEV_PROJECT))
    log(f"volumes du projet {PROJECT} : {targets or 'aucun'} ; volumes de développement protégés : {sorted(protected)}")
    for name in targets:
        if not name.startswith(f"{PROJECT}_") or name in protected:
            raise SystemExit(f"[e2e] ARRÊT : volume inattendu {name!r} — aucune suppression effectuée.")
    run([*compose, "down", "-v", "--remove-orphans"], env=env, check=False)
    remaining = volumes(PROJECT)
    if remaining:
        raise SystemExit(f"[e2e] volumes E2E restants : {remaining}")


# --- Préparation ----------------------------------------------------------------------------------------------


def write_env(workdir: Path) -> tuple[Path, dict[str, str]]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = secrets.token_hex(24) if value.strip() == "__GENERATE__" else value.strip()
    values.update(EDGE)
    values.update({
        "RBI_HTTP_HOST_PORT": str(HTTP_PORT),
        "RBI_HTTPS_HOST_PORT": str(HTTPS_PORT),
        "RBI_MAILPIT_UI_HOST_PORT": str(MAILPIT_PORT),
        "RBI_FRONTEND_URL": f"http://localhost:{HTTP_PORT}",
    })
    path = workdir / "e2e.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return path, values


def build_frontend(dist: Path) -> None:
    """Frontend construit en mode intégré (API réelle, MSW pour les seuls modules reportés), Node 24 du projet."""
    script = (
        "set -e; mkdir /work; tar -C /src --exclude=node_modules --exclude=dist --exclude=test-results "
        "--exclude=playwright-report -cf - . | tar -C /work -xf -; cd /work; "
        "npm ci --no-audit --no-fund --loglevel=error; "
        "VITE_APP_ENV=demo VITE_API_MOCKS=deferred npx vite build --outDir /out --emptyOutDir"
    )
    run(["docker", "run", "--rm", "-v", f"{ROOT / 'frontend'}:/src:ro", "-v", f"{dist}:/out", NODE_IMAGE, "sh", "-c", script])


def make_certificate(tls: Path) -> None:
    run(["docker", "run", "--rm", "--entrypoint", "openssl", "-v", f"{tls}:/tls", OPENSSL_IMAGE, "req", "-x509",
         "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost", "-keyout", "/tls/key.pem",
         "-out", "/tls/cert.pem", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], capture=True)


# --- Contrôles TLS ----------------------------------------------------------------------------------------------


def https_get(path: str, cafile: Path, *, max_version: ssl.TLSVersion | None = None) -> tuple[int, dict[str, str], str]:
    context = ssl.create_default_context(cafile=str(cafile))
    if max_version:
        context.maximum_version = max_version
    connection = http.client.HTTPSConnection("localhost", HTTPS_PORT, context=context, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    response.read()
    version = connection.sock.version() if connection.sock else ""
    headers = {k.lower(): v for k, v in response.getheaders()}
    connection.close()
    return response.status, headers, version or ""


def openssl_client(protocol: str, extra: list[str]) -> subprocess.CompletedProcess[str]:
    return run(["docker", "run", "--rm", "--network", f"{PROJECT}_edge", "--entrypoint", "sh", OPENSSL_IMAGE, "-c",
                f"echo | openssl s_client -connect proxy:443 -servername localhost {protocol} {' '.join(extra)} 2>&1"],
               check=False, capture=True)


def tls_checks(cafile: Path) -> None:
    connection = http.client.HTTPConnection("localhost", HTTP_PORT, timeout=10)
    connection.request("GET", "/connexion?x=1")
    redirect = connection.getresponse()
    location = redirect.getheader("Location", "")
    record("HTTP → HTTPS (301)", redirect.status == 301 and location == f"https://localhost:{HTTPS_PORT}/connexion?x=1",
           f"{redirect.status} {location}")
    record("aucun HSTS sur HTTP", redirect.getheader("Strict-Transport-Security") is None)
    connection.close()

    status, headers, version = https_get("/connexion", cafile)
    record("page HTTPS (TLS 1.3 négocié)", status == 200 and version == "TLSv1.3", f"{status} {version}")
    record("HSTS sur HTTPS", headers.get("strict-transport-security") == "max-age=31536000; includeSubDomains")
    record("CSP sur HTTPS", "frame-ancestors 'none'" in headers.get("content-security-policy", ""))
    status, headers, version = https_get("/api/v1/auth/csrf", cafile, max_version=ssl.TLSVersion.TLSv1_2)
    cookie = headers.get("set-cookie", "")
    record("TLS 1.2 accepté", status == 204 and version == "TLSv1.2", version)
    record("cookie CSRF « Secure » derrière TLS", "csrftoken=" in cookie and "Secure" in cookie, cookie.split(";")[0][:20] + "…")
    status, headers, _ = https_get("/api/v1/health/ready", cafile)
    record("API derrière TLS, HSTS compris", status == 200 and "strict-transport-security" in headers, str(status))

    # Client autorisé à proposer TLS 1.1 (SECLEVEL=0) : le refus vient donc du SERVEUR (alerte protocol_version).
    tls11 = openssl_client("-tls1_1", ["-cipher", "DEFAULT@SECLEVEL=0"])
    record("TLS 1.1 refusé par le serveur", "alert protocol version" in tls11.stdout,
           next((line for line in tls11.stdout.splitlines() if "alert" in line or "error" in line), tls11.stdout[-160:]).strip())
    tls12 = openssl_client("-tls1_2", [])
    record("TLS 1.2 (openssl)", "TLSv1.2" in tls12.stdout and "Cipher is (NONE)" not in tls12.stdout)
    tls13 = openssl_client("-tls1_3", [])
    record("TLS 1.3 (openssl)", "TLSv1.3" in tls13.stdout and "Cipher is (NONE)" not in tls13.stdout)

    for name in ("key.pem", "cert.pem"):
        record(f"{name} hors du dépôt", not (ROOT / name).exists() and not str(cafile).startswith(str(ROOT)))


# --- Programme principal ------------------------------------------------------------------------------------------


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # console Windows
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep", action="store_true", help="ne pas détruire l'environnement à la fin")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="rbi-e2e-"))
    dist, tls = workdir / "dist", workdir / "tls"
    dist.mkdir()
    tls.mkdir()
    env_file, values = write_env(workdir)
    os.environ.pop("COMPOSE_PROJECT_NAME", None)
    compose = ["docker", "compose", "-p", PROJECT, "--env-file", str(env_file), "-f", "docker-compose.yml",
               "-f", "infra/e2e/compose.e2e.yml"]
    compose_tls = [*compose, "-f", "infra/e2e/compose.tls.yml"]
    compose_env = {**os.environ, "RBI_E2E_DIST": str(dist), "RBI_E2E_TLS_DIR": str(tls)}
    dev_before = volume_identity(volumes(DEV_PROJECT))
    log(f"répertoire de travail (hors dépôt) : {workdir}")
    log(f"volumes de développement avant : {dev_before}")

    def compose_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return run(command, env=compose_env, **kwargs)  # type: ignore[arg-type]

    status = 1
    try:
        if volumes(PROJECT):  # reste d'une exécution interrompue : même vérification avant suppression
            safe_teardown(compose, compose_env)
        log("construction du frontend (mode intégré)…")
        build_frontend(dist)
        make_certificate(tls)
        log("démarrage de l'environnement E2E (HTTP)…")
        compose_run([*compose, "up", "-d", "--wait", "--build"])
        super_password = f"E2e-{secrets.token_urlsafe(18)}"
        compose_run([*compose, "run", "--rm", "-T", "migrate", "python", "manage.py", "create_super_admin",
                     "--email", SUPER_ADMIN, "--password-stdin"], input_text=super_password, capture=True)
        # Sans saut de ligne : sous Windows, un « \n » écrit dans le tube devient « \r\n » et le « \r » resterait
        # dans le mot de passe enregistré (constat P2.10, rapport §8).
        log("Super Administrateur fictif créé (commande serveur).")

        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        playwright_env = {
            **os.environ,
            "RBI_E2E_BASE_URL": f"http://localhost:{HTTP_PORT}",
            "RBI_E2E_MAILPIT_URL": f"http://127.0.0.1:{MAILPIT_PORT}",
            "RBI_E2E_SUPERADMIN_EMAIL": SUPER_ADMIN,
            "RBI_E2E_SUPERADMIN_PASSWORD": super_password,
            "RBI_E2E_USER_PASSWORD": f"E2e-{secrets.token_urlsafe(18)}",
            "RBI_E2E_PROXY_IP": values["RBI_EDGE_PROXY_IP"],
        }
        playwright = run([npx, "playwright", "test", "-c", "playwright.integrated.config.ts"], env=playwright_env,
                         cwd=ROOT / "frontend", check=False)
        record("Playwright — parcours intégrés", playwright.returncode == 0, f"code {playwright.returncode}")

        log("bascule de Nginx et de l'API en TLS (certificat autosigné temporaire)…")
        compose_run([*compose_tls, "up", "-d", "--wait", "proxy", "api"])
        tls_checks(tls / "cert.pem")
        status = 0 if all(ok for _, ok, _ in RESULTS) else 1
    finally:
        if args.keep:
            log(f"environnement conservé (--keep) : docker compose -p {PROJECT} --env-file {env_file} …")
        else:
            safe_teardown(compose, compose_env)
            shutil.rmtree(workdir, ignore_errors=True)
        dev_after = volume_identity(volumes(DEV_PROJECT))
        record("volumes de développement intacts", dev_after == dev_before and bool(dev_before), json.dumps(dev_after))
        if any(not ok for _, ok, _ in RESULTS):
            status = 1
    print(json.dumps({"results": [{"check": n, "ok": ok, "detail": d} for n, ok, d in RESULTS]}, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
