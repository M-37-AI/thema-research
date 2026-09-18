#!/usr/bin/env python3
"""Rendert einen Lauf zu einer einzigen, in sich geschlossenen HTML-Datei (runs/<lauf>/report.html).

- Prüft report.json vorher mit validate.py (Fehler -> Abbruch).
- Ersetzt jeden Verweis {ref:<datei>#<pointer>} durch den formatierten Wert
  (Schätzungen mit „~“) und eine nummerierte Fußnote; gleiche Quellen teilen sich eine Fußnote.
- Die Exhibits sind reines SVG/HTML (keine JavaScript-Bibliothek): offline lesbar,
  druckbar, klein. Ein kurzes Skript ergänzt nur Tooltips.
- Liegt lektorat.json im Lauf, werden die sprachlich überarbeiteten Texte eingesetzt
  (die Originaldateien bleiben unverändert); --ohne-lektorat rendert die Rohfassung.

Exit-Code: 0 = report.html geschrieben, 1 = Fehler.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from gemeinsam import PROJEKT, ToolFehler, ausfuehren, kennzahlen_pfad, lauf_ordner, lies_json, lies_lauf
from validate import REF_MUSTER, json_pointer_aufloesen, validiere_datei, verweis_aufloesen

AKZENT = "#0b2545"   # Marine – Überschriften, Kernwerte (Text, keine Datenfarbe)
MITTEL = "#3e6ea8"   # Links und Fußnoten
GOLD = "#b8912f"     # Akzentlinie


# ---------------------------------------------------------------- Zahlen und Fußnoten

def zahl_text(wert: float) -> str:
    """Deutsche Zahlformatierung mit sinnvoller Genauigkeit."""
    if wert == 0:
        return "0"
    betrag = abs(wert)
    stellen = 0 if betrag >= 100 else 1 if betrag >= 1 else 2
    text = f"{wert:,.{stellen}f}".replace(",", " ").replace(".", ",")
    if stellen and text.endswith(",0"):
        text = text[:-2]
    return text


def einheit_text(einheit: str) -> str:
    if einheit in ("%", "% Umsatz"):
        return " %"
    if einheit == "x":
        return "x"
    return " " + einheit


def formatiere(zahl: dict) -> str:
    if zahl.get("wert") is None:
        return "n. v."
    praefix = "~" if zahl.get("typ") == "schaetzung" else ""
    return f"{praefix}{zahl_text(zahl['wert'])}{einheit_text(zahl.get('einheit', ''))}"


class Fussnoten:
    """Sammelt Quellen; gleiche Quelle (URL bzw. Begründung) -> gleiche Nummer."""

    def __init__(self):
        self.liste: list[dict] = []
        self._index: dict[tuple, int] = {}

    def nummer(self, zahl: dict) -> int:
        if zahl.get("typ") == "schaetzung":
            schluessel = ("s", zahl.get("begruendung", ""))
            eintrag = {"art": "Schätzung", "text": zahl.get("begruendung", ""), "quelle": None}
        else:
            schluessel = ("b", zahl.get("quelle", ""))
            eintrag = {"art": "Quelle", "text": zahl.get("herausgeber") or "", "quelle": zahl.get("quelle")}
        if schluessel not in self._index:
            eintrag.update(nr=len(self.liste) + 1, abgerufen=zahl.get("abgerufen"), hinweis=zahl.get("hinweis"))
            self.liste.append(eintrag)
            self._index[schluessel] = eintrag["nr"]
        return self._index[schluessel]

    def aussage(self, beleg: dict) -> int:
        """Qualitativer Beleg {aussage, quelle}."""
        return self.nummer({"typ": "berichtet", "quelle": beleg["quelle"], "herausgeber": beleg.get("aussage", "")})

    def marke(self, zahl: dict) -> Markup:
        nr = self.nummer(zahl)
        return Markup(f'<sup class="fn"><a href="#fn{nr}" id="r{nr}">{nr}</a></sup>')

    def zahl(self, zahl: dict | None) -> Markup:
        """Formatierter Wert plus Fußnote – für Tabellen."""
        if not zahl:
            return Markup('<span class="leer">–</span>')
        klasse = "zahl schaetzung" if zahl.get("typ") == "schaetzung" else "zahl"
        return Markup(f'<span class="{klasse}">{html.escape(formatiere(zahl))}</span>') + self.marke(zahl)


def text_zu_html(text: str, lauf: Path, fn: Fussnoten) -> Markup:
    """Report-Text: HTML-escapen, Verweise einsetzen, Absätze bilden."""
    teile, pos = [], 0
    for treffer in REF_MUSTER.finditer(text):
        teile.append(html.escape(text[pos:treffer.start()]))
        zahl = verweis_aufloesen(lauf, treffer.group(1), treffer.group(2))
        teile.append(str(fn.zahl(zahl)))
        pos = treffer.end()
    teile.append(html.escape(text[pos:]))
    absaetze = [a.strip() for a in "".join(teile).split("\n\n") if a.strip()]
    return Markup("".join(f"<p>{a.replace(chr(10), '<br>')}</p>" for a in absaetze))


# ---------------------------------------------------------------- Exhibits (SVG/HTML, ohne JavaScript-Bibliothek)
#
# Gestaltung nach dem Dataviz-Verfahren: Form nach Aufgabe, Farben aus einer
# validierten Palette (validate_palette.js: Slots 1–3 bestehen alle Paar-Prüfungen
# auf Weiß; Aqua < 3:1 Kontrast -> immer direkt beschriftet + Tabelle), dünne Marken,
# Haarlinien-Raster, Balken ab null, Tooltips nur als Ergänzung.

SERIE = {"Kernprofiteur": "#2a78d6", "Zulieferer": "#eb6834", "Mitlaeufer": "#1baf7a"}  # feste Zuordnung je Rolle
BALKEN = "#2a78d6"          # eine Reihe -> Slot 1
BALKEN_SCHAETZUNG = "#86b6ef"  # heller Schritt derselben Rampe (+ „~“ als Zweitkodierung)
RASTER, ACHSE, LEISE = "#e1e0d9", "#c3c2b7", "#898781"


def _in_mrd_usd(zahl: dict) -> float | None:
    treffer = re.fullmatch(r"\s*(Tsd|Mio|Mrd|Bio)\.?\s+USD\s*", zahl.get("einheit", ""))
    if not treffer or zahl.get("wert") is None:
        return None
    return zahl["wert"] * {"Tsd": 1e-6, "Mio": 1e-3, "Mrd": 1.0, "Bio": 1e3}[treffer.group(1)]


def _runde_skala(maximum: float) -> list[float]:
    """Saubere Achsenwerte 0 … ≥ maximum (1-2-2,5-5-Raster, 4–6 Schritte, kleinste Obergrenze gewinnt)."""
    if maximum <= 0:
        return [0, 1]
    beste = None
    for schritte in (4, 5, 6):
        roh = maximum / schritte
        groesse = 10 ** math.floor(math.log10(roh))
        schritt = next(f * groesse for f in (1, 2, 2.5, 5, 10) if f * groesse >= roh)
        achse = [round(i * schritt, 6) for i in range(int(math.ceil(maximum / schritt - 1e-9)) + 1)]
        if beste is None or achse[-1] < beste[-1]:
            beste = achse
    return beste


FIRMENZUSAETZE = {"inc", "inc.", "corp", "corp.", "corporation", "co.", "ltd", "ltd.", "ag", "se", "sa", "plc", "nv",
                  "systems", "technology", "technologies", "group", "holdings", "shenzhen", "&", "company"}


def kurzname(name: str) -> str:
    """„Shenzhen Inovance Technology“ -> „Inovance“, „Rockwell Automation, Inc.“ -> „Rockwell Automation“."""
    woerter = [w for w in name.replace(",", " ").split() if w.lower() not in FIRMENZUSAETZE]
    return " ".join(woerter[:2]) or name


def erster_satz(text: str) -> str:
    treffer = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return treffer.group(1) if treffer else text


def exhibit_spanne(markt: dict, fn: Fussnoten) -> dict:
    """Exhibit 1: Marktschätzungen als waagerechte Balken ab null, eine Reihe."""
    zeilen, ausgelassen = [], []
    for s in markt["schaetzungen"]:
        mrd = _in_mrd_usd(s["marktgroesse"])
        if mrd is None:
            ausgelassen.append(f"{s['herausgeber']} ({s['marktgroesse'].get('einheit')})")
            continue
        zeilen.append({"herausgeber": s["herausgeber"], "jahr": s["jahr_prognose"],
                       "abgrenzung": erster_satz(s.get("abgrenzung", "")),
                       "mrd": mrd, "schaetzung": s["marktgroesse"].get("typ") == "schaetzung",
                       "wert": fn.zahl(s["marktgroesse"])})
    if not zeilen:
        return {"zeilen": [], "achse": [], "ausgelassen": ausgelassen}
    zeilen.sort(key=lambda z: -z["mrd"])
    achse = _runde_skala(max(z["mrd"] for z in zeilen))
    for z in zeilen:
        z["breite"] = round(100 * z["mrd"] / achse[-1], 2)
    return {"zeilen": zeilen, "achse": [{"wert": zahl_text(a), "pos": round(100 * a / achse[-1], 2)} for a in achse],
            "ausgelassen": ausgelassen, "farbe": BALKEN, "farbe_schaetzung": BALKEN_SCHAETZUNG}


def exhibit_kette(markt: dict, universum: dict | None, shortlist: set[str], fn: Fussnoten) -> list[dict]:
    """Exhibit 2: Segmente mit ihren Kandidaten – eine Tabelle statt einer Treemap (Fläche trüge keine Information)."""
    status = {k["ticker"]: k for k in (universum or {}).get("kandidaten", []) if "status" in k}
    zeilen = []
    for seg in markt["segmente"]:
        kandidaten = []
        for k in seg["kandidaten"]:
            info = status.get(k["ticker"], {})
            if k["ticker"] in shortlist:
                art, hinweis = "gewaehlt", "In der Auswahl"
            elif info.get("status") == "ausgeschlossen":
                art, hinweis = "ausgeschlossen", f"Ausgeschlossen: {info.get('grund', '')}"
            else:
                art, hinweis = "gescreent", "Gescreent, nicht ausgewählt"
            kandidaten.append({"name": k["name"], "ticker": k["ticker"], "art": art, "hinweis": hinweis})
        kandidaten.sort(key=lambda k: {"gewaehlt": 0, "gescreent": 1, "ausgeschlossen": 2}[k["art"]])
        zeilen.append({"name": seg["name"], "beschreibung": seg["beschreibung"], "marge": seg["margenprofil"],
                       "groesse": fn.zahl(seg["marktgroesse"]) if seg.get("marktgroesse") else None,
                       "kandidaten": kandidaten})
    return zeilen


def exhibit_streuung(firmen: list[dict]) -> str:
    """Exhibit 4: Themen-Exposure (x) gegen EV/Umsatz (y) als SVG-Streudiagramm, drei Rollen-Farben."""
    punkte = [f for f in firmen if f["exposure"].get("wert") is not None and f["ev_umsatz"] is not None]
    if not punkte:
        return ""
    breite, hoehe = 760, 380
    links, rechts, oben, unten = 56, 28, 18, 52
    pb, ph = breite - links - rechts, hoehe - oben - unten
    y_achse = _runde_skala(max(f["ev_umsatz"] for f in punkte))
    y_max = y_achse[-1]
    x = lambda v: links + pb * max(0, min(v, 100)) / 100  # noqa: E731
    y = lambda v: oben + ph * (1 - max(0, v) / y_max)  # noqa: E731
    e = html.escape
    teile = [f'<svg class="streuung" viewBox="0 0 {breite} {hoehe}" role="img" '
             f'aria-label="Streudiagramm: Themen-Exposure gegen EV/Umsatz für {len(punkte)} Unternehmen">']
    for v in y_achse:  # Raster + y-Beschriftung
        teile.append(f'<line x1="{links}" x2="{links + pb}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{ACHSE if v == 0 else RASTER}" stroke-width="1"/>')
        teile.append(f'<text x="{links - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="achse">{zahl_text(v)}x</text>')
    for v in range(0, 101, 25):
        teile.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{oben}" y2="{oben + ph}" stroke="{RASTER}" stroke-width="1"/>')
        teile.append(f'<text x="{x(v):.1f}" y="{oben + ph + 18}" text-anchor="middle" class="achse">{v} %</text>')
    teile.append(f'<text x="{links + pb / 2}" y="{hoehe - 6}" text-anchor="middle" class="achsentitel">Themen-Exposure (Anteil des Umsatzes)</text>')
    teile.append(f'<text transform="translate(14 {oben + ph / 2}) rotate(-90)" text-anchor="middle" class="achsentitel">EV / Umsatz</text>')
    # Punkte: erst weißer Ring, dann Marke; Schätzung = offener Kreis. Unsichtbarer Trefferkreis ≥ 24 px.
    for f in sorted(punkte, key=lambda f: -(f["mkap_usd"] or 0)):
        cx, cy, farbe = x(f["exposure"]["wert"]), y(f["ev_umsatz"]), SERIE.get(f["rolle"], LEISE)
        geschaetzt = f["exposure"].get("typ") == "schaetzung"
        tipp = (f"{f['name']} ({f['ticker']})|Rolle: {f['rolle_text']}|"
                f"Exposure: {'~' if geschaetzt else ''}{zahl_text(f['exposure']['wert'])} %"
                f"{' (Schätzung)' if geschaetzt else ''}|EV/Umsatz: {zahl_text(f['ev_umsatz'])}x"
                + (f"|Marktkapitalisierung: {zahl_text(f['mkap_usd'])} Mrd USD" if f["mkap_usd"] else ""))
        fuellung = "#ffffff" if geschaetzt else farbe
        teile.append(f'<g class="punkt" tabindex="0" data-tipp="{e(tipp)}">'
                     f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="12" fill="transparent"/>'
                     f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="#ffffff"/>'
                     f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.5" fill="{fuellung}" stroke="{farbe}" stroke-width="2.5"/>'
                     + (f'<text x="{cx - 10:.1f}" y="{cy - 9:.1f}" text-anchor="end" class="marke">'
                        if cx > links + pb * 0.8 else f'<text x="{cx + 10:.1f}" y="{cy - 9:.1f}" class="marke">')
                     + f'{e(kurzname(f["name"]))}</text></g>')
    teile.append("</svg>")
    return "".join(teile)


# ---------------------------------------------------------------- Daten sammeln

class Lektorat:
    """Setzt die Fassungen aus lektorat.json in die geladenen Daten ein (nur im Speicher)."""

    def __init__(self, lauf: Path, aktiv: bool = True):
        daten = lies_json(lauf / "lektorat.json") if aktiv and (lauf / "lektorat.json").is_file() else {}
        self.glossar = daten.get("glossar", [])
        self.ersetzungen: dict[str, list[tuple[str, str]]] = {}
        for e in daten.get("ersetzungen", []):
            self.ersetzungen.setdefault(e["datei"], []).append((e["pfad"], e["text"]))
        self.anzahl = sum(len(v) for v in self.ersetzungen.values())

    def anwenden(self, datei: str, daten):
        if daten is None or datei not in self.ersetzungen:
            return daten
        daten = copy.deepcopy(daten)
        for pfad, text in self.ersetzungen[datei]:
            *eltern_pfad, letzter = pfad[1:].split("/")
            eltern = json_pointer_aufloesen(daten, "/" + "/".join(eltern_pfad)) if eltern_pfad else daten
            letzter = letzter.replace("~1", "/").replace("~0", "~")
            eltern[int(letzter) if isinstance(eltern, list) else letzter] = text
        return daten


def _optional(pfad: Path) -> dict | None:
    return lies_json(pfad) if pfad.is_file() else None


def firmen_laden(lauf: Path, markt: dict, fn: Fussnoten, lektorat: Lektorat) -> list[dict]:
    segmente = {s["id"]: s["name"] for s in markt["segmente"]}
    firmen = []
    for datei in sorted((lauf / "firmen").glob("*.json")):
        f = lektorat.anwenden(f"firmen/{datei.name}", lies_json(datei))
        kz_datei = kennzahlen_pfad(lauf, f["kennzahlen_datei"])
        kz = lies_json(kz_datei) if kz_datei.is_file() else {"kennzahlen": {}}
        k = kz.get("kennzahlen", {})
        firmen.append({
            "name": f["name"], "ticker": f["ticker"], "segment": segmente.get(f["segment_id"], f["segment_id"]),
            "rolle": f["rolle_im_thema"], "rolle_text": f["rolle_im_thema"].replace("ae", "ä"),
            "exposure": f["themen_exposure"], "exposure_html": fn.zahl(f["themen_exposure"]),
            "wachstum": fn.zahl(k.get("umsatzwachstum_yoy")) if k.get("umsatzwachstum_yoy") else None,
            "marge": fn.zahl(k.get("operative_marge")) if k.get("operative_marge") else None,
            "ev_umsatz_html": fn.zahl(k.get("ev_umsatz")) if k.get("ev_umsatz") else None,
            "ev_umsatz": (k.get("ev_umsatz") or {}).get("wert"),
            "mkap_usd": (kz.get("marktkapitalisierung_usd") or {}).get("wert"),
            "ueberzeugung": f["ueberzeugung"], "geschaeftsmodell": f["geschaeftsmodell"],
            "bull_case": f["bull_case"], "bear_case": f["bear_case"],
            "widerlegen": f["was_uns_widerlegen_wuerde"], "kennzahlen_fehlen": not kz_datei.is_file(),
        })
    return firmen


def tuersteher_statistik(lauf: Path) -> dict | None:
    log = lauf / "gate-log.jsonl"
    if not log.is_file():
        return None
    eintraege = [json.loads(z) for z in log.read_text(encoding="utf-8").splitlines() if z.strip()]
    abgelehnt = [e for e in eintraege if e["entscheidung"] == "abgelehnt"]
    fehlerarten = Counter()
    for e in abgelehnt:
        for f in e.get("fehler", []) or [e.get("grund", "")]:
            pfad, _, art = f.rpartition(": ")
            feld = re.sub(r"\[\d+\]", "", pfad).rsplit(".", 1)[-1]  # letzter Feldname ohne Listenindex
            art = f"{feld}: {art}" if feld and feld != "(Wurzel)" else art
            art = re.sub(r"'[^']*'", "…", art)  # konkrete Werte ausblenden
            art = re.sub(r"\(\d+\)", "(n)", art)
            fehlerarten[art] += 1
    je_teammate = Counter(e["teammate"] for e in abgelehnt)
    return {"pruefungen": len(eintraege), "akzeptiert": len(eintraege) - len(abgelehnt),
            "abgelehnt": len(abgelehnt), "je_teammate": je_teammate.most_common(),
            "fehlerarten": fehlerarten.most_common(5),
            "dateien": sorted({e["datei"].split("/", 2)[-1] for e in abgelehnt})}


def daten_sammeln(lauf: Path, mit_lektorat: bool = True) -> dict:
    fn = Fussnoten()
    lektorat = Lektorat(lauf, mit_lektorat)
    lauf_info = lies_lauf(lauf)
    markt = lektorat.anwenden("markt.json", lies_json(lauf / "markt.json"))
    report = lektorat.anwenden("report.json", lies_json(lauf / "report.json"))
    universum = _optional(lauf / "universum.json")
    shortlist_datei = _optional(lauf / "shortlist.json")
    redteam = lektorat.anwenden("redteam.json", _optional(lauf / "redteam.json"))
    bottom_up = _optional(lauf / "bottom_up.json")
    t = lambda text: text_zu_html(text, lauf, fn)  # noqa: E731

    # Reihenfolge der Fußnoten folgt dem Lesefluss: erst die Texte, dann Tabellen
    kopf = {"titel": report["titel"], "kernaussage": t(report["kernaussage"]), "these": t(report["these"])}
    abschnitte = {k: t(v) for k, v in report["abschnitte"].items()}

    schaetzungen = [{"herausgeber": s["herausgeber"], "jahr": s["jahr_prognose"], "wert": fn.zahl(s["marktgroesse"]),
                     "cagr": fn.zahl(s.get("cagr")) if s.get("cagr") else None, "abgrenzung": s.get("abgrenzung", "")}
                    for s in markt["schaetzungen"]]

    def punkte(liste):
        ergebnis = []
        for p in liste:
            belege = [fn.zahl(b) if "wert" in b else Markup(html.escape(b["aussage"])) + Markup(
                f'<sup class="fn"><a href="#fn{fn.aussage(b)}">{fn.aussage(b)}</a></sup>') for b in p["belege"]]
            ergebnis.append({"titel": p["titel"], "beschreibung": p["beschreibung"], "belege": belege})
        return ergebnis

    shortlist = {s["ticker"] for s in (shortlist_datei or {}).get("auswahl", [])}
    spanne = exhibit_spanne(markt, fn)
    segmente = exhibit_kette(markt, universum, shortlist, fn)
    firmen = firmen_laden(lauf, markt, fn, lektorat)

    einwaende, antworten = [], {a["einwand_ref"]: a for a in report["antworten_auf_einwaende"]}
    for e in (redteam or {}).get("einwaende", []):
        antwort = antworten.get(e["id"])
        einwaende.append({**e, "beleg_html": (fn.zahl(e["beleg"]) if "wert" in e.get("beleg", {}) else
                                              Markup(html.escape(e["beleg"]["aussage"])) + Markup(f'<sup class="fn"><a href="#fn{fn.aussage(e["beleg"])}">{fn.aussage(e["beleg"])}</a></sup>')
                                              ) if e.get("beleg") else None,
                          "antwort": antwort, "unbeantwortet": e["schwere"] == "hoch" and not antwort})
    einwaende.sort(key=lambda e: ({"hoch": 0, "mittel": 1, "niedrig": 2}[e["schwere"]], int(e["id"][1:])))

    bu = None
    if bottom_up:
        bu = {"art": bottom_up["art"], "summe": fn.zahl(bottom_up["summe_themenumsatz"]),
              "unten": fn.zahl(bottom_up["top_down_unten"]), "oben": fn.zahl(bottom_up["top_down_oben"]),
              "abdeckung_min": fn.zahl(bottom_up["abdeckung_bei_oberer_schaetzung"]),
              "abdeckung_max": fn.zahl(bottom_up["abdeckung_bei_unterer_schaetzung"]),
              "firmen": bottom_up["firmen"], "hinweise": bottom_up["hinweise"]}

    return {
        "lauf": lauf_info, "thema": lauf_info.get("thema") or markt["thema"], "datum": lauf_info.get("datum") or markt["datum"],
        "fiktiv": bool(lauf_info.get("fiktiv")), "kopf": kopf, "abschnitte": abschnitte,
        "schaetzungen": schaetzungen, "spanne": spanne,
        "treiber": punkte(markt["treiber"]), "huerden": punkte(markt["huerden"]),
        "segmente": segmente,
        "firmen": firmen, "streuung": Markup(exhibit_streuung(firmen)), "serie": SERIE,
        "einwaende": einwaende, "redteam": redteam, "bottom_up": bu,
        "beobachtungspunkte": [t(b) for b in report["beobachtungspunkte"]],
        "universum": universum["statistik"] if universum else None,
        "score_formel": universum["regeln"]["score_formel"] if universum else None,
        "gate": tuersteher_statistik(lauf), "fussnoten": fn.liste,
        "gold": GOLD, "mittel": MITTEL,
        "glossar": lektorat.glossar, "lektorat_anzahl": lektorat.anzahl,
        "akzent": AKZENT,
    }


def rendern(lauf: Path, mit_lektorat: bool = True) -> Path:
    zu_pruefen = ["report.json"]
    if mit_lektorat and (lauf / "lektorat.json").is_file():
        zu_pruefen.append("lektorat.json")
    for name in zu_pruefen:
        fehler, warnungen = validiere_datei(lauf / name)
        if fehler:
            raise ToolFehler(f"{name} ist ungültig – erst korrigieren:\n  " + "\n  ".join(fehler))
        for w in warnungen:
            print(f"! {name}: {w}")
    umgebung = Environment(loader=FileSystemLoader(PROJEKT / "templates"), autoescape=select_autoescape(["html", "j2"]),
                           trim_blocks=True, lstrip_blocks=True)
    seite = umgebung.get_template("report.html.j2").render(**daten_sammeln(lauf, mit_lektorat))
    ziel = lauf / ("report.html" if mit_lektorat else "report-ohne-lektorat.html")
    ziel.write_text(seite, encoding="utf-8")
    return ziel


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rendert runs/<lauf>/report.json zu einer eigenständigen HTML-Datei.",
                                     epilog="Beispiel: python3 tools/render.py tests/fixtures/beispiel-lauf --open")
    parser.add_argument("lauf", help="Lauf-Ordner mit report.json, markt.json, firmen/ …")
    parser.add_argument("--open", action="store_true", help="Report danach im Browser öffnen")
    parser.add_argument("--ohne-lektorat", action="store_true",
                        help="Rohfassung ohne lektorat.json rendern (-> report-ohne-lektorat.html, zum Vergleichen)")
    args = parser.parse_args(argv)

    ziel = rendern(lauf_ordner(args.lauf), not args.ohne_lektorat)
    groesse = ziel.stat().st_size / 1e6
    print(f"✓ {ziel} geschrieben ({groesse:.1f} MB, offline lesbar)")
    if args.open:
        befehl = {"darwin": "open", "win32": "start"}.get(sys.platform, "xdg-open")
        subprocess.run([befehl, str(ziel)], check=False)
    return 0


if __name__ == "__main__":
    ausfuehren(main)
