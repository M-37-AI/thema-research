#!/usr/bin/env python3
"""Screening: Kandidaten aus markt.json -> universum.json mit Status, Score und Shortlist-Vorschlag.

Ablauf:
  1. Alle Kandidaten aus markt.json sammeln; doppelte Ticker werden ausgeschlossen.
  2. Kennzahlen je Ticker per kennzahlen.py (Import) holen.
  3. Ausschlussregeln aus tools/screen_regeln.json anwenden.
  4. Transparenten Score berechnen (Formel steht in der Regeldatei).
  5. Shortlist-Vorschlag per Rundlauf über die Segmente.

Exit-Code: 0 = universum.json geschrieben, 1 = Fehler (z. B. markt.json fehlt).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gemeinsam import ToolFehler, ausfuehren, lauf_ordner, lies_json, schreib_json
from kennzahlen import KennzahlenFehler, hole_kennzahlen

REGELN = Path(__file__).resolve().parent / "screen_regeln.json"


def _wert(kz: dict, feld: str):
    """Liest einen Wert aus der Kennzahlen-Datei (oberste Ebene oder unter 'kennzahlen')."""
    objekt = kz.get(feld) or kz.get("kennzahlen", {}).get(feld)
    return None if objekt is None else objekt.get("wert")


def kandidaten_sammeln(markt: dict) -> list[dict]:
    gesehen: dict[str, str] = {}
    liste = []
    for segment in markt["segmente"]:
        for k in segment["kandidaten"]:
            ticker = k["ticker"].strip().upper()
            eintrag = {"ticker": ticker, "name": k["name"], "segment_id": segment["id"],
                       "segment_name": segment["name"], "begruendung_kette": k["begruendung"]}
            if ticker in gesehen:
                eintrag.update(status="ausgeschlossen", grund=f"Duplikat (bereits im Segment {gesehen[ticker]})")
            else:
                gesehen[ticker] = segment["id"]
            liste.append(eintrag)
    return liste


def ausschluss_pruefen(eintrag: dict, kz: dict, regeln: dict) -> str | None:
    for feld in regeln["pflichtfelder"]:
        if _wert(kz, feld) is None:
            return f"Datenlücke: {feld} fehlt"
    mkap = _wert(kz, "marktkapitalisierung_usd")
    grenze = regeln["min_marktkapitalisierung_usd_mrd"]
    if mkap < grenze:
        return f"Marktkapitalisierung {mkap:.2f} Mrd USD unter Mindestwert {grenze} Mrd USD"
    return None


def perzentilrang(werte: list[float], x: float) -> float:
    """Anteil der Werte, die kleiner sind (Gleichstand zählt halb) – 0 bis 1."""
    if len(werte) <= 1:
        return 0.5
    kleiner = sum(1 for w in werte if w < x)
    gleich = sum(1 for w in werte if w == x) - 1
    return (kleiner + 0.5 * gleich) / (len(werte) - 1)


def scores_berechnen(aufgenommen: list[dict], regeln: dict) -> None:
    gewichte, richtung, neutral = regeln["gewichte"], regeln["hoeher_ist_besser"], regeln["fehlender_wert"]
    for feld in gewichte:
        vorhanden = [e["kennzahlen"][feld] for e in aufgenommen if e["kennzahlen"][feld] is not None]
        for e in aufgenommen:
            wert = e["kennzahlen"][feld]
            if wert is None:
                rang = neutral
                e.setdefault("hinweise", []).append(f"{feld} fehlt – neutral mit {neutral} gewertet")
            else:
                rang = perzentilrang(vorhanden, wert)
                if not richtung[feld]:
                    rang = 1 - rang
            e.setdefault("score_teile", {})[feld] = round(rang, 3)
    for e in aufgenommen:
        e["score"] = round(100 * sum(gewichte[f] * e["score_teile"][f] for f in gewichte), 1)


def shortlist_vorschlagen(aufgenommen: list[dict], anzahl: int) -> list[dict]:
    je_segment: dict[str, list[dict]] = {}
    for e in sorted(aufgenommen, key=lambda e: -e["score"]):
        je_segment.setdefault(e["segment_id"], []).append(e)
    auswahl, runde = [], 0
    while len(auswahl) < anzahl and any(len(l) > runde for l in je_segment.values()):
        # in jeder Runde die Segmente nach dem Score ihres Kandidaten sortieren
        diese_runde = sorted((l[runde] for l in je_segment.values() if len(l) > runde), key=lambda e: -e["score"])
        for e in diese_runde:
            if len(auswahl) < anzahl:
                auswahl.append({"ticker": e["ticker"], "name": e["name"], "segment_id": e["segment_id"],
                                "score": e["score"], "runde": runde + 1})
        runde += 1
    return auswahl


def screenen(ordner: Path, offline: bool) -> dict:
    markt = lies_json(ordner / "markt.json")
    regeln = lies_json(REGELN)
    liste = kandidaten_sammeln(markt)

    for e in liste:
        if e.get("status"):
            continue
        if sys.stdout.isatty():
            print(f"  hole Kennzahlen {e['ticker']:<12}", end="\r")
        try:
            kz = hole_kennzahlen(e["ticker"], offline=offline)
        except KennzahlenFehler as f:
            e.update(status="ausgeschlossen", grund=f"keine Daten: {f}")
            continue
        e["kennzahlen_datei"] = f"data/kennzahlen/{e['ticker']}.json"
        e["kennzahlen"] = {f: _wert(kz, f) for f in
                           ["marktkapitalisierung_usd", "umsatz_ttm_usd", "umsatzwachstum_yoy", "operative_marge", "ev_umsatz"]}
        grund = ausschluss_pruefen(e, kz, regeln["ausschluss"])
        if grund:
            e.update(status="ausgeschlossen", grund=grund)
        else:
            e["status"] = "aufgenommen"
    if sys.stdout.isatty():
        print(" " * 40, end="\r")

    aufgenommen = [e for e in liste if e["status"] == "aufgenommen"]
    scores_berechnen(aufgenommen, regeln["score"])
    return {
        "thema": markt["thema"],
        "datum": markt["datum"],
        "regeln": {"datei": "tools/screen_regeln.json", "score_formel": regeln["score"]["formel"],
                   "ausschluss": regeln["ausschluss"]},
        "statistik": {"kandidaten": len(liste), "aufgenommen": len(aufgenommen),
                      "ausgeschlossen": len(liste) - len(aufgenommen)},
        "kandidaten": liste,
        "shortlist_vorschlag": shortlist_vorschlagen(aufgenommen, regeln["shortlist"]["anzahl"]),
    }


def _z(wert, stellen=1):
    return "–" if wert is None else f"{wert:,.{stellen}f}".replace(",", " ")


def tabelle(universum: dict) -> None:
    vorschlag = {s["ticker"] for s in universum["shortlist_vorschlag"]}
    print(f"\n{'':2}{'Ticker':<11}{'Name':<26}{'Segment':<20}{'MKap $Mrd':>10}{'Wachst.%':>9}{'Op.M.%':>8}{'EV/U':>6}{'Score':>7}")
    print("  " + "─" * 95)
    aufgenommen = sorted((e for e in universum["kandidaten"] if e["status"] == "aufgenommen"),
                         key=lambda e: (e["segment_id"], -e["score"]))
    for e in aufgenommen:
        k = e["kennzahlen"]
        marke = "★ " if e["ticker"] in vorschlag else "  "
        print(f"{marke}{e['ticker']:<11}{e['name'][:25]:<26}{e['segment_name'][:19]:<20}"
              f"{_z(k['marktkapitalisierung_usd']):>10}{_z(k['umsatzwachstum_yoy']):>9}"
              f"{_z(k['operative_marge']):>8}{_z(k['ev_umsatz'], 2):>6}{e['score']:>7.1f}")
    ausgeschlossen = [e for e in universum["kandidaten"] if e["status"] == "ausgeschlossen"]
    if ausgeschlossen:
        print("\n  Ausgeschlossen:")
        for e in ausgeschlossen:
            print(f"  ✗ {e['ticker']:<11}{e['name'][:25]:<26}{e['grund']}")
    s = universum["statistik"]
    print(f"\n  {s['kandidaten']} Kandidaten, {s['aufgenommen']} aufgenommen, {s['ausgeschlossen']} ausgeschlossen. "
          f"★ = Shortlist-Vorschlag ({len(vorschlag)})")
    print(f"  Score: {universum['regeln']['score_formel']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Screent alle Kandidaten aus markt.json und schreibt universum.json.",
                                     epilog="Beispiel: python3 tools/screen.py runs/robotik-2026-09-18")
    parser.add_argument("lauf", help="Lauf-Ordner mit markt.json")
    parser.add_argument("--offline", action="store_true", help="Kennzahlen nur aus dem Cache lesen")
    args = parser.parse_args(argv)

    ordner = lauf_ordner(args.lauf)
    universum = screenen(ordner, args.offline)
    if universum["statistik"]["aufgenommen"] == 0:
        schreib_json(ordner / "universum.json", universum)
        raise ToolFehler("Kein Kandidat hat das Screening bestanden – Ticker in kette.json prüfen.")
    schreib_json(ordner / "universum.json", universum)
    tabelle(universum)
    print(f"\n✓ {ordner / 'universum.json'} geschrieben")
    return 0


if __name__ == "__main__":
    ausfuehren(main)
