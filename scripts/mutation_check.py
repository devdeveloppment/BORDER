"""Contre-épreuves par mutation, reproductibles, dans un environnement Docker JETABLE (projet « rbi-mut »).

    py scripts/mutation_check.py scripts/mutations/p2_11.json --report docs/phases/phase-2/mutations/P2.11.md

Pour chaque mutation du catalogue, une à la fois :
1. la cible doit apparaître exactement une fois (sinon : aucune mutation, arrêt) ; empreinte SHA-256 du
   fichier ;
2. application, puis exécution des seuls tests détecteurs attendus (pytest, base de test isolée) ;
3. restauration de l'original (toujours, bloc finally) et vérification que l'empreinte est identique.

Avant la première mutation, les tests détecteurs doivent réussir sur le code non muté (exécution de
référence) ; après la dernière, toutes les empreintes initiales sont revérifiées. Le rapport distingue le
résultat ATTENDU (catalogue) du résultat OBSERVÉ (sortie de pytest) ; il ne contient ni secret ni valeur
d'environnement.

Isolation : projet Docker distinct, volumes et réseau propres, détruits à la fin après vérification de leur
étiquette (garde-fous de scripts/e2e.py) ; l'environnement de développement (projet « rbi ») n'est jamais
visé.
Bibliothèque standard uniquement (Python 3.10+).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e  # garde-fous partagés : volumes, environnement jetable

ROOT = e2e.ROOT
e2e.PROJECT = "rbi-mut"
e2e.EDGE = {
    "RBI_EDGE_SUBNET": "172.29.91.0/28",
    "RBI_EDGE_PROXY_IP": "172.29.91.2",
    "RBI_EDGE_DYNAMIC_RANGE": "172.29.91.8/29",
}
e2e.HTTP_PORT, e2e.HTTPS_PORT, e2e.MAILPIT_PORT = 28080, 28443, 28025
SERVICES = ["db", "redis", "storage", "mailpit"]
FAILED = re.compile(r"^FAILED (\S+?)(?:\[[^\]]*\])?(?: - .*)?$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return out.stdout.strip()


def run_pytest(compose: list[str], env: dict[str, str], tests: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        [
            *compose,
            "--profile",
            "tools",
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "backend",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "-rf",
            *sorted(set(tests)),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout + result.stderr


def failed_tests(output: str) -> set[str]:
    return {m.group(1) for line in output.splitlines() if (m := FAILED.match(line.strip()))}


def apply_mutation(path: Path, target: str, replacement: str) -> bytes:
    original = path.read_bytes()
    text = original.decode("utf-8")
    crlf = "\r\n" in text
    normalized = text.replace("\r\n", "\n")
    count = normalized.count(target)
    if count != 1:
        raise SystemExit(
            f"[mutation] cible trouvée {count} fois dans {path.name} (attendu 1) : aucune mutation"
        )
    mutated = normalized.replace(target, replacement)
    path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated).encode("utf-8"))
    return original


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("catalog")
    parser.add_argument("--report", help="fichier Markdown du rapport (relatif à la racine du dépôt)")
    parser.add_argument("--only", help="identifiants séparés par des virgules")
    args = parser.parse_args()

    catalog = json.loads((ROOT / args.catalog).read_text(encoding="utf-8"))
    mutations = catalog["mutations"]
    if args.only:
        wanted = set(args.only.split(","))
        mutations = [m for m in mutations if m["id"] in wanted]
    files = sorted({m["file"] for m in mutations})
    initial = {f: sha256(ROOT / f) for f in files}
    all_detectors = [t for m in mutations for t in m["detectors"]]

    workdir = Path(tempfile.mkdtemp(prefix="rbi-mut-"))
    (workdir / "dist").mkdir()
    (workdir / "tls").mkdir()
    env_file, _ = e2e.write_env(workdir)
    os.environ.pop("COMPOSE_PROJECT_NAME", None)
    compose = [
        "docker",
        "compose",
        "-p",
        e2e.PROJECT,
        "--env-file",
        str(env_file),
        "-f",
        "docker-compose.yml",
        "-f",
        "infra/e2e/compose.e2e.yml",
    ]
    env = {**os.environ, "RBI_E2E_DIST": str(workdir / "dist"), "RBI_E2E_TLS_DIR": str(workdir / "tls")}
    dev_before = e2e.volume_identity(e2e.volumes(e2e.DEV_PROJECT))
    started = datetime.datetime.now(datetime.timezone.utc)  # noqa: UP017 (Python 3.10, comme e2e.py)
    results: list[dict[str, object]] = []
    baseline = (-1, "")
    status = 1
    try:
        if e2e.volumes(e2e.PROJECT):
            e2e.safe_teardown(compose, env)
        e2e.run([*compose, "up", "-d", "--wait", *SERVICES], env=env)
        baseline = run_pytest(compose, env, all_detectors)
        e2e.log(f"référence (sans mutation) : code {baseline[0]}")
        if baseline[0] != 0:
            raise SystemExit(
                "[mutation] les tests détecteurs échouent sans mutation : arrêt, rien n'est muté"
            )
        for m in mutations:
            path = ROOT / str(m["file"])
            before = sha256(path)
            original = apply_mutation(path, str(m["target"]), str(m["replacement"]))
            try:
                code, output = run_pytest(compose, env, list(m["detectors"]))
            finally:
                path.write_bytes(original)
            restored = sha256(path) == before
            observed = failed_tests(output)
            expected = {str(t) for t in m["detectors"]}
            caught = expected & observed
            messages = [str(x) for x in m.get("expected_messages", [])]
            missing_messages = [x for x in messages if x not in output]
            verdict = (
                "détectée"
                if caught == expected and not missing_messages
                else "partiellement détectée"
                if caught
                else "NON détectée"
            )
            results.append(
                {
                    "id": m["id"],
                    "origin": m["origin"],
                    "control": m["control"],
                    "code": code,
                    "expected": sorted(expected),
                    "failed": sorted(observed),
                    "caught": sorted(caught),
                    "missing_messages": missing_messages,
                    "verdict": verdict,
                    "restored": restored,
                }
            )
            e2e.log(
                f"{m['id']} : {verdict} ({len(caught)}/{len(expected)}) ; restauration "
                f"{'identique' if restored else 'DIFFÉRENTE'}"
            )
            if not restored:
                raise SystemExit(f"[mutation] {m['id']} : empreinte différente après restauration : arrêt")
        final_ok = all(sha256(ROOT / f) == h for f, h in initial.items())
        status = 0 if final_ok and all(r["verdict"] == "détectée" for r in results) else 1
    finally:
        e2e.safe_teardown(compose, env)
        shutil.rmtree(workdir, ignore_errors=True)
        dev_after = e2e.volume_identity(e2e.volumes(e2e.DEV_PROJECT))
        intact = dev_after == dev_before
        final = {f: sha256(ROOT / f) == h for f, h in initial.items()}
        if args.report:
            write_report(ROOT / args.report, catalog, args.catalog, results, baseline, started, final, intact)
        print(
            json.dumps(
                {"results": results, "files_restored": final, "dev_volumes_intact": intact},
                ensure_ascii=False,
                indent=2,
            )
        )
    return status


def write_report(
    path: Path,
    catalog: dict[str, object],
    catalog_path: str,
    results: list[dict[str, object]],
    baseline: tuple[int, str],
    started: datetime.datetime,
    final: dict[str, bool],
    intact: bool,
) -> None:
    dirty = git("status", "--porcelain")
    lines = [
        f"# Contre-épreuves par mutation — {catalog['phase']} (exécution du {started:%d/%m/%Y %H:%M} UTC)",
        "",
        "Rapport généré par `scripts/mutation_check.py`. Il décrit une exécution réelle ; les résultats",
        "historiques ne sont pas recopiés ici.",
        "",
        f"- **Catalogue** : `{catalog_path}`",
        f"- **Code** : commit `{git('rev-parse', '--short', 'HEAD')}`"
        + (" avec modifications non commitées" if dirty else " (arbre propre)"),
        "- **Environnement** : projet Docker jetable `rbi-mut`, base de test pytest-django, détruit en fin "
        f"d'exécution ; volumes de développement {'inchangés' if intact else 'MODIFIÉS'}",
        f"- **Référence sans mutation** : tests détecteurs {'réussis' if baseline[0] == 0 else 'en échec'} "
        f"(code {baseline[0]})",
        "",
        "| Réf. | Origine | Contrôle | Détecteurs attendus | Détecteurs en échec (observé) | Verdict "
        "| Restauration |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        expected = "<br>".join(f"`{str(t).split('::')[-1]}`" for t in r["expected"])  # type: ignore[union-attr]
        caught = "<br>".join(f"`{str(t).split('::')[-1]}`" for t in r["caught"]) or "aucun"  # type: ignore[union-attr]
        note = f" ; message attendu absent : {r['missing_messages']}" if r["missing_messages"] else ""
        lines.append(
            f"| {r['id']} | {r['origin']} | {r['control']} | {expected} | {caught} | "
            f"**{r['verdict']}**{note} | {'identique' if r['restored'] else 'DIFFÉRENTE'} |"
        )
    lines += [
        "",
        "Empreintes finales identiques à l'état initial : "
        + ", ".join(f"`{f}` {'oui' if ok else 'NON'}" for f, ok in final.items()),
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
