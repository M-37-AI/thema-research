#!/usr/bin/env python3
"""Türsteher (Hook TaskCreated): Jede Aufgabe braucht eine Ergebnisdatei im Titel.

Konvention:  [runs/<lauf>/<datei>.json] Titel
Ausnahme:    Titel, die mit "Koordination:" beginnen.

Verstößt ein Titel dagegen, endet das Skript mit Exit 2; Claude Code löscht die
Aufgabe dann und gibt die Meldung auf stderr an den Agenten zurück.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

PFAD_MUSTER = re.compile(r"\[runs/[^\]\s]+\.json\]")
AUSNAHME = "Koordination:"


def pruefen(eingabe: dict) -> tuple[int, str]:
    titel = (eingabe.get("task_subject") or "").strip()
    if titel.startswith(AUSNAHME) or PFAD_MUSTER.search(titel):
        return 0, ""
    return 2, (
        f"Türsteher: Aufgabentitel „{titel}“ folgt nicht der Konvention.\n"
        "Jede Aufgabe nennt ihre Ergebnisdatei im Titel, z. B. "
        "„[runs/robotik-2026-09-18/kette.json] Wertschöpfungskette“.\n"
        f"Aufgaben ohne eigene Datei beginnen mit „{AUSNAHME}“."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Hook TaskCreated: erzwingt die Titelkonvention [runs/….json]. Liest Hook-JSON von stdin.",
        epilog='Beispiel: echo \'{"task_subject": "Recherche"}\' | python3 tools/gate_create.py   # -> Exit 2')
    parser.parse_args(argv)
    try:
        eingabe = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Türsteher: Hook-Eingabe ist kein gültiges JSON ({e.msg}).", file=sys.stderr)
        return 1
    code, meldung = pruefen(eingabe)
    if meldung:
        print(meldung, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
