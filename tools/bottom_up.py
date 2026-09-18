#!/usr/bin/env python3
"""Bottom-up-Check: Summe der Themen-Umsätze der Shortlist gegen die Top-down-Spanne.

Themen-Umsatz je Firma = umsatz_ttm_usd × themen_exposure / 100
Abdeckungsquote       = Summe Themen-Umsatz / Marktgröße (untere und obere Schätzung)

Das Ergebnis ist ausdrücklich eine Näherung: nur die Shortlist, TTM-Umsätze
gegen teils künftige Marktprognosen, und geschätzte Exposures fließen ein.
Alle Ergebnisse sind Zahl-Objekte (typ "schaetzung") und damit im Report referenzierbar.

Exit-Code: 0 = bottom_up.json geschrieben, 1 = Fehler (z. B. keine Firmen-Dateien).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re

from gemeinsam import ToolFehler, ausfuehren, kennzahlen_pfad, lauf_ordner, lies_json, schreib_json

FAKTOR = {"Tsd": 1e-6, "Mio": 1e-3, "Mrd": 1.0, "Bio": 1e3}


def in_mrd_usd(zahl: dict) -> float | None:
    """'120 Mrd USD' -> 120.0; andere Währungen oder Einheiten -> None."""
    treffer = re.fullmatch(r"\s*(Tsd|Mio|Mrd|Bio)\.?\s+USD\s*", zahl.get("einheit", ""))
    if not treffer or zahl.get("wert") is None:
        return None
    return zahl["wert"] * FAKTOR[treffer.group(1)]


def schaetzung(wert, einheit: str, begruendung: str) -> dict:
    return {"wert": None if wert is None else round(wert, 3), "einheit": einheit, "typ": "schaetzung",
            "begruendung": begruendung, "abgerufen": dt.date.today().isoformat(),
            "herausgeber": "eigene Berechnung (bottom_up.py)"}


def berechnen(ordner) -> dict:
    firmen_dateien = sorted((ordner / "firmen").glob("*.json"))
    if not firmen_dateien:
        raise ToolFehler(f"Keine Firmen-Dateien in {ordner / 'firmen'}")
    markt = lies_json(ordner / "markt.json")

    firmen, hinweise = [], []
    for datei in firmen_dateien:
        firma = lies_json(datei)
        kz_pfad = kennzahlen_pfad(ordner, firma["kennzahlen_datei"])
        if not kz_pfad.is_file():
            hinweise.append(f"{firma['ticker']}: Kennzahlen-Datei fehlt ({firma['kennzahlen_datei']}) – nicht berücksichtigt")
            continue
        umsatz = lies_json(kz_pfad)["umsatz_ttm_usd"]["wert"]
        exposure = firma["themen_exposure"]
        if umsatz is None or exposure.get("wert") is None:
            hinweise.append(f"{firma['ticker']}: Umsatz oder Exposure fehlt – nicht berücksichtigt")
            continue
        firmen.append({"ticker": firma["ticker"], "name": firma["name"], "segment_id": firma["segment_id"],
                       "umsatz_ttm_usd_mrd": umsatz, "exposure_pct": exposure["wert"],
                       "exposure_typ": exposure["typ"],
                       "themen_umsatz_usd_mrd": round(umsatz * exposure["wert"] / 100, 3)})

    summe = sum(f["themen_umsatz_usd_mrd"] for f in firmen)
    geschaetzt = [f["ticker"] for f in firmen if f["exposure_typ"] == "schaetzung"]

    top_down = []
    for s in markt["schaetzungen"]:
        mrd = in_mrd_usd(s["marktgroesse"])
        if mrd is None:
            hinweise.append(f"Schätzung {s['herausgeber']}: Einheit „{s['marktgroesse'].get('einheit')}“ nicht in USD umrechenbar – nicht berücksichtigt")
            continue
        top_down.append({"herausgeber": s["herausgeber"], "jahr_prognose": s["jahr_prognose"], "mrd_usd": mrd})
    if not top_down:
        raise ToolFehler("Keine Top-down-Schätzung in USD vorhanden – Vergleich nicht möglich")

    unten = min(top_down, key=lambda t: t["mrd_usd"])
    oben = max(top_down, key=lambda t: t["mrd_usd"])
    jahre = sorted({t["jahr_prognose"] for t in top_down})
    basis = (f"Summe aus {len(firmen)} Firmen der Shortlist (Umsatz TTM × Themen-Exposure); "
             f"{len(geschaetzt)} der Exposures sind Schätzungen.")

    return {
        "art": "Näherung – nur Shortlist, TTM-Umsätze gegen Prognosen für " + ", ".join(map(str, jahre)),
        "summe_themenumsatz": schaetzung(summe, "Mrd USD", basis),
        "top_down_unten": schaetzung(unten["mrd_usd"], "Mrd USD", f"Niedrigste Top-down-Schätzung ({unten['herausgeber']}, Prognosejahr {unten['jahr_prognose']})."),
        "top_down_oben": schaetzung(oben["mrd_usd"], "Mrd USD", f"Höchste Top-down-Schätzung ({oben['herausgeber']}, Prognosejahr {oben['jahr_prognose']})."),
        "abdeckung_bei_unterer_schaetzung": schaetzung(100 * summe / unten["mrd_usd"], "%", "Anteil des Bottom-up-Themenumsatzes an der niedrigsten Marktschätzung. " + basis),
        "abdeckung_bei_oberer_schaetzung": schaetzung(100 * summe / oben["mrd_usd"], "%", "Anteil des Bottom-up-Themenumsatzes an der höchsten Marktschätzung. " + basis),
        "firmen": firmen,
        "exposure_geschaetzt": geschaetzt,
        "top_down": top_down,
        "hinweise": hinweise,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Vergleicht die Summe der Themen-Umsätze der Shortlist mit der Top-down-Spanne.",
                                     epilog="Beispiel: python3 tools/bottom_up.py runs/robotik-2026-09-18")
    parser.add_argument("lauf", help="Lauf-Ordner mit markt.json und firmen/")
    args = parser.parse_args(argv)

    ordner = lauf_ordner(args.lauf)
    ergebnis = berechnen(ordner)
    schreib_json(ordner / "bottom_up.json", ergebnis)

    print(f"\n  {'Ticker':<11}{'Umsatz $Mrd':>12}{'Exposure %':>12}{'':>3}{'Thema $Mrd':>11}")
    for f in ergebnis["firmen"]:
        marke = "~" if f["exposure_typ"] == "schaetzung" else " "
        print(f"  {f['ticker']:<11}{f['umsatz_ttm_usd_mrd']:>12.2f}{f['exposure_pct']:>12.1f}{marke:>3}{f['themen_umsatz_usd_mrd']:>11.2f}")
    e = ergebnis
    print(f"\n  Bottom-up-Summe:   {e['summe_themenumsatz']['wert']:.2f} Mrd USD")
    print(f"  Top-down-Spanne:   {e['top_down_unten']['wert']:.1f} – {e['top_down_oben']['wert']:.1f} Mrd USD")
    print(f"  Abdeckung:         {e['abdeckung_bei_oberer_schaetzung']['wert']:.1f} % – {e['abdeckung_bei_unterer_schaetzung']['wert']:.1f} %")
    print(f"  ({e['art']}; ~ = Exposure geschätzt)")
    for h in e["hinweise"]:
        print(f"  ! {h}")
    print(f"\n✓ {ordner / 'bottom_up.json'} geschrieben")
    return 0


if __name__ == "__main__":
    ausfuehren(main)
