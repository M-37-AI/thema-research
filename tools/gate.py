#!/usr/bin/env python3
"""Türsteher (Hook TaskCompleted): Eine Aufgabe ist erst erledigt, wenn ihre Datei gültig ist.

Liest das Hook-JSON von stdin (task_subject, task_description, teammate_name, cwd, …)
und sucht im Titel – ersatzweise in der Beschreibung – einen Pfad der Form [runs/….json].

  kein Pfad             -> Exit 0 (Aufgabe ohne Datei, z. B. Koordination)
  Datei fehlt           -> Meldung auf stderr, Exit 2 (Aufgabe bleibt offen)
  Validierungsfehler    -> Fehlerliste auf stderr, Exit 2
  gültig                -> Exit 0

Jede Entscheidung wird an runs/<lauf>/gate-log.jsonl angehängt.
Bei Exit 2 gibt Claude Code den stderr-Text als Feedback an den Agenten zurück.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import validiere_datei  # noqa: E402

PFAD_MUSTER = re.compile(r"\[(runs/[^\]\s]+\.json)\]")
KORREKTUR = "Korrigiere die Datei und markiere die Aufgabe erneut als erledigt."


def projekt_ordner(eingabe: dict) -> Path:
    """Aufgabenpfade sind relativ zum Projekt; CLAUDE_PROJECT_DIR hat Vorrang vor cwd."""
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or eingabe.get("cwd") or os.getcwd())


def finde_pfad(eingabe: dict) -> str | None:
    for feld in ("task_subject", "task_description"):
        treffer = PFAD_MUSTER.search(eingabe.get(feld) or "")
        if treffer:
            return treffer.group(1)
    return None


def protokollieren(projekt: Path, pfad: str, eingabe: dict, entscheidung: str, fehler: list[str], grund: str) -> None:
    teile = Path(pfad).parts  # ("runs", "<lauf>", ...)
    if len(teile) < 3:
        return
    log = projekt / teile[0] / teile[1] / "gate-log.jsonl"
    if not log.parent.is_dir():
        return
    eintrag = {
        "zeit": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "ereignis": eingabe.get("hook_event_name", "TaskCompleted"),
        "entscheidung": entscheidung,
        "grund": grund,
        "teammate": eingabe.get("teammate_name") or "lead",
        "datei": pfad,
        "fehler_anzahl": len(fehler),
        "fehler": fehler[:20],
        "task_id": eingabe.get("task_id"),
        "task_subject": eingabe.get("task_subject"),
    }
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


def pruefen(eingabe: dict) -> tuple[int, str]:
    """Gibt (Exit-Code, Meldung für stderr) zurück."""
    pfad = finde_pfad(eingabe)
    if pfad is None:
        return 0, ""
    projekt = projekt_ordner(eingabe)
    if ".." in Path(pfad).parts:
        return 2, f"Türsteher: ungültiger Pfad {pfad} (kein „..“ erlaubt)."

    datei = projekt / pfad
    if not datei.is_file():
        protokollieren(projekt, pfad, eingabe, "abgelehnt", [], "Datei fehlt")
        return 2, (f"Türsteher: Die Datei {pfad} existiert nicht. "
                   "Schreibe sie, validiere sie mit python3 tools/validate.py und markiere die Aufgabe dann erneut als erledigt.")

    fehler, _ = validiere_datei(datei)
    if fehler:
        protokollieren(projekt, pfad, eingabe, "abgelehnt", fehler, "Validierungsfehler")
        liste = "\n".join(f"  - {f}" for f in fehler)
        return 2, f"Türsteher: {pfad} ist ungültig ({len(fehler)} Fehler):\n{liste}\n{KORREKTUR}"

    protokollieren(projekt, pfad, eingabe, "akzeptiert", [], "gültig")
    return 0, ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Hook TaskCompleted: prüft die Datei [runs/….json] aus dem Aufgabentitel. Liest Hook-JSON von stdin.",
        epilog='Beispiel: echo \'{"task_subject": "[runs/x/kette.json] Kette"}\' | python3 tools/gate.py')
    parser.parse_args(argv)
    try:
        eingabe = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Türsteher: Hook-Eingabe ist kein gültiges JSON ({e.msg}) – Aufgabe wird nicht geprüft.", file=sys.stderr)
        return 1  # nicht blockierender Fehler
    code, meldung = pruefen(eingabe)
    if meldung:
        print(meldung, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
