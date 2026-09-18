#!/usr/bin/env python3
"""Führt markt-groesse.json, treiber.json und kette.json zu markt.json zusammen.

Die drei Eingaben werden vorher validiert; das Ergebnis ebenfalls.
Thema und Datum kommen aus lauf.json (sonst aus markt-groesse.json bzw. heute).

Exit-Code: 0 = markt.json gültig geschrieben, 1 = Eingabe fehlt oder ungültig.
"""
from __future__ import annotations

import argparse
import datetime as dt

from gemeinsam import ToolFehler, ausfuehren, lauf_ordner, lies_json, lies_lauf, schreib_json
from validate import validiere_datei

EINGABEN = ["markt-groesse.json", "treiber.json", "kette.json"]


def zusammenfuehren(ordner) -> dict:
    fehler = []
    for name in EINGABEN:
        f, _ = validiere_datei(ordner / name)
        fehler += [f"{name}: {x}" for x in f]
    if fehler:
        raise ToolFehler("Eingaben ungültig – erst korrigieren:\n  " + "\n  ".join(fehler))

    groesse, treiber, kette = (lies_json(ordner / n) for n in EINGABEN)
    lauf = lies_lauf(ordner)
    themen = {groesse["thema"], treiber["thema"], kette["thema"]}
    thema = lauf.get("thema") or groesse["thema"]
    if len(themen) > 1:
        print(f"! Hinweis: unterschiedliche Themen-Bezeichnungen {sorted(themen)} – verwende „{thema}“")

    return {
        "thema": thema,
        "datum": lauf.get("datum") or dt.date.today().isoformat(),
        "schaetzungen": groesse["schaetzungen"],
        "treiber": treiber["treiber"],
        "huerden": treiber["huerden"],
        "segmente": kette["segmente"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Führt die Phase-1-Ergebnisse eines Laufs zu markt.json zusammen.",
                                     epilog="Beispiel: python3 tools/merge_markt.py runs/robotik-2026-09-18")
    parser.add_argument("lauf", help="Lauf-Ordner, z. B. runs/robotik-2026-09-18")
    args = parser.parse_args(argv)

    ordner = lauf_ordner(args.lauf)
    markt = zusammenfuehren(ordner)
    ziel = ordner / "markt.json"
    schreib_json(ziel, markt)
    fehler, _ = validiere_datei(ziel)
    if fehler:
        raise ToolFehler("markt.json ist ungültig:\n  " + "\n  ".join(fehler))
    kandidaten = sum(len(s["kandidaten"]) for s in markt["segmente"])
    print(f"✓ {ziel} geschrieben: {len(markt['schaetzungen'])} Schätzungen, "
          f"{len(markt['treiber'])} Treiber, {len(markt['huerden'])} Hürden, "
          f"{len(markt['segmente'])} Segmente, {kandidaten} Kandidaten")
    return 0


if __name__ == "__main__":
    ausfuehren(main)
