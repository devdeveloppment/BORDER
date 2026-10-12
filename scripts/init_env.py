"""Crée ou complète le fichier .env de développement à partir de .env.example.

Chaque valeur ``__GENERATE__`` est remplacée par un secret aléatoire (``secrets.token_hex``,
alphabet hexadécimal : sûr dans une URL ``redis://`` comme dans une commande shell).

Si .env existe déjà, seules les variables absentes sont ajoutées : les valeurs en place ne sont
jamais modifiées (les mots de passe PostgreSQL sont fixés à la première initialisation du volume).

Usage : py scripts/init_env.py   (Python 3.10+, bibliothèque standard uniquement)
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

PLACEHOLDER = "__GENERATE__"
ROOT = Path(__file__).resolve().parent.parent


def render(line: str) -> str:
    if line.rstrip().endswith("=" + PLACEHOLDER):
        return line.replace(PLACEHOLDER, secrets.token_hex(24))
    return line


def variable_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def main() -> int:
    template_lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    target = ROOT / ".env"

    if not target.exists():
        target.write_text("\n".join(render(line) for line in template_lines) + "\n", encoding="utf-8", newline="\n")
        print(f"{target} cree.")
        return 0

    existing = target.read_text(encoding="utf-8")
    present = {name for line in existing.splitlines() if (name := variable_name(line))}
    missing = [line for line in template_lines if (name := variable_name(line)) and name not in present]
    if not missing:
        print(f"{target} est complet : rien n'est modifie.")
        return 0

    addition = "\n".join(render(line) for line in missing)
    separator = "" if existing.endswith("\n") else "\n"
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{separator}\n# Ajouté par scripts/init_env.py\n{addition}\n")
    names = ", ".join(name for line in missing if (name := variable_name(line)))
    print(f"{target} complete : {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
