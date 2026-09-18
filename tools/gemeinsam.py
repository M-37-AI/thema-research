"""Kleine Hilfsfunktionen, die mehrere Tools teilen."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent


class ToolFehler(Exception):
    """Fehler mit verständlicher Meldung; das Tool beendet sich mit Exit 1."""


def lauf_ordner(pfad: str | Path) -> Path:
    ordner = Path(pfad)
    if not ordner.is_dir():
        raise ToolFehler(f"Lauf-Ordner nicht gefunden: {ordner}")
    return ordner


def lies_json(pfad: Path) -> dict:
    if not pfad.is_file():
        raise ToolFehler(f"Datei fehlt: {pfad}")
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ToolFehler(f"{pfad}: kein gültiges JSON (Zeile {e.lineno}): {e.msg}")


def schreib_json(pfad: Path, daten: dict) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lies_lauf(ordner: Path) -> dict:
    """lauf.json (thema, datum) – optional; leeres Dict, wenn nicht vorhanden."""
    datei = ordner / "lauf.json"
    return lies_json(datei) if datei.is_file() else {}


def ausfuehren(main) -> None:
    """Startet main() und wandelt ToolFehler in Meldung + Exit 1."""
    sys.stdout.reconfigure(line_buffering=True)
    try:
        sys.exit(main())
    except ToolFehler as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
