#!/usr/bin/env python3
"""Sammelt alle Texte eines Laufs, die im Report erscheinen – als Arbeitsvorlage für den Lektor.

Schreibt runs/<lauf>/lektorat-vorlage.json:
  {"texte": [{"datei": "report.json", "pfad": "/these", "original": "…"}, …]}

Der Lektor übernimmt datei und pfad unverändert, schreibt seine Fassung als "text"
und legt das Ergebnis als lektorat.json ab. Stellen, die er nicht verbessern kann,
lässt er weg.

Exit-Code: 0 = Vorlage geschrieben, 1 = Fehler (z. B. report.json fehlt).
"""
from __future__ import annotations

import argparse

from gemeinsam import ToolFehler, ausfuehren, lauf_ordner, lies_json, schreib_json

# Welche Textfelder der Renderer anzeigt – je Datei als (Pfad-Muster). "*" steht für jeden Listenindex.
FELDER = {
    "report.json": ["/titel", "/kernaussage", "/these", "/abschnitte/markt", "/abschnitte/treiber_und_huerden",
                    "/abschnitte/wertschoepfung", "/abschnitte/unternehmen", "/abschnitte/risiken",
                    "/antworten_auf_einwaende/*/antwort", "/antworten_auf_einwaende/*/konsequenz",
                    "/beobachtungspunkte/*"],
    "markt.json": ["/schaetzungen/*/abgrenzung", "/treiber/*/titel", "/treiber/*/beschreibung",
                   "/treiber/*/belege/*/aussage", "/huerden/*/titel", "/huerden/*/beschreibung",
                   "/huerden/*/belege/*/aussage", "/segmente/*/beschreibung", "/segmente/*/margenprofil/begruendung"],
    "redteam.json": ["/einwaende/*/einwand", "/einwaende/*/beleg/aussage", "/bottom_up_kommentar", "/gesamturteil"],
    "firmen/*": ["/geschaeftsmodell", "/ueberzeugung/begruendung", "/bull_case/*", "/bear_case/*",
                 "/was_uns_widerlegen_wuerde"],
}


def _stellen(daten, teile: list[str], pfad: str = ""):
    """Löst ein Pfad-Muster mit * gegen die Daten auf und liefert (pfad, text)."""
    if not teile:
        if isinstance(daten, str):
            yield pfad, daten
        return
    kopf, rest = teile[0], teile[1:]
    if kopf == "*":
        if isinstance(daten, list):
            for i, element in enumerate(daten):
                yield from _stellen(element, rest, f"{pfad}/{i}")
    elif isinstance(daten, dict) and kopf in daten:
        yield from _stellen(daten[kopf], rest, f"{pfad}/{kopf}")


def vorlage(ordner) -> list[dict]:
    if not (ordner / "report.json").is_file():
        raise ToolFehler(f"report.json fehlt in {ordner} – das Lektorat kommt nach dem Report")
    texte = []
    for datei, muster in FELDER.items():
        pfade = sorted((ordner / "firmen").glob("*.json")) if datei == "firmen/*" else [ordner / datei]
        for pfad in pfade:
            if not pfad.is_file():
                continue
            name = f"firmen/{pfad.name}" if datei == "firmen/*" else datei
            daten = lies_json(pfad)
            for m in muster:
                for stelle, text in _stellen(daten, m.strip("/").split("/")):
                    texte.append({"datei": name, "pfad": stelle, "original": text})
    return texte


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sammelt alle im Report sichtbaren Texte als Vorlage für das Lektorat.",
                                     epilog="Beispiel: python3 tools/lektorat_vorlage.py runs/robotik-2026-09-18")
    parser.add_argument("lauf", help="Lauf-Ordner mit report.json")
    args = parser.parse_args(argv)
    ordner = lauf_ordner(args.lauf)
    texte = vorlage(ordner)
    schreib_json(ordner / "lektorat-vorlage.json", {"texte": texte})
    je_datei: dict[str, int] = {}
    for t in texte:
        schluessel = "firmen/*" if t["datei"].startswith("firmen/") else t["datei"]
        je_datei[schluessel] = je_datei.get(schluessel, 0) + 1
    zeichen = sum(len(t["original"]) for t in texte)
    print(f"✓ {ordner / 'lektorat-vorlage.json'}: {len(texte)} Textstellen, {zeichen:_} Zeichen".replace("_", "."))
    for d, n in je_datei.items():
        print(f"    {d:<14} {n:>4}")
    return 0


if __name__ == "__main__":
    ausfuehren(main)
