#!/usr/bin/env python3
"""Rendert einen Lauf zu einer einzigen, in sich geschlossenen HTML-Datei (runs/<lauf>/report.html).

- Prüft report.json vorher mit validate.py (Fehler -> Abbruch).
- Ersetzt jeden Verweis {ref:<datei>#<pointer>} durch den formatierten Wert
  (Schätzungen mit „~“) und eine nummerierte Fußnote; gleiche Quellen teilen sich eine Fußnote.
- Plotly wird inline eingebettet, der Report funktioniert offline.
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

AKZENT = "#0b2545"   # Marine – Titelband, Überschriften, Kernwerte
MITTEL = "#3e6ea8"   # zweite Datenfarbe
GOLD = "#b8912f"     # Akzentlinie
GRAU = "#8a94a6"
HELL = "#c5d3e6"
SCHRIFT = "Helvetica Neue, Helvetica, Arial, sans-serif"


# ---------------------------------------------------------------- Zahlen und Fußnoten

def zahl_text(wert: float) -> str:
    """Deutsche Zahlformatierung mit sinnvoller Genauigkeit."""
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


# ---------------------------------------------------------------- Charts

def _layout(**extra) -> dict:
    basis = dict(template="simple_white", font=dict(family=SCHRIFT, size=13, color="#1a1a1a"),
                 margin=dict(l=10, r=20, t=10, b=40), paper_bgcolor="white", plot_bgcolor="white")
    basis.update(extra)
    return basis


def _in_mrd_usd(zahl: dict) -> float | None:
    treffer = re.fullmatch(r"\s*(Tsd|Mio|Mrd|Bio)\.?\s+USD\s*", zahl.get("einheit", ""))
    if not treffer or zahl.get("wert") is None:
        return None
    return zahl["wert"] * {"Tsd": 1e-6, "Mio": 1e-3, "Mrd": 1.0, "Bio": 1e3}[treffer.group(1)]


def chart_spanne(markt: dict) -> tuple[str, list[str]]:
    """Chart 1: Schätzungen je Herausgeber als Bereichsbalken über die Gesamtspanne."""
    import plotly.graph_objects as go
    punkte, ausgelassen = [], []
    for s in markt["schaetzungen"]:
        mrd = _in_mrd_usd(s["marktgroesse"])
        if mrd is None:
            ausgelassen.append(f"{s['herausgeber']} ({s['marktgroesse'].get('einheit')})")
            continue
        punkte.append((f"{s['herausgeber']} ({s['jahr_prognose']})", mrd, s["marktgroesse"].get("typ")))
    if not punkte:
        return "", ausgelassen
    punkte.sort(key=lambda p: p[1])
    unten, oben = punkte[0][1], punkte[-1][1]
    namen = [p[0] for p in punkte]
    fig = go.Figure()
    # Gesamtspanne als heller Hintergrundbalken, jede Schätzung als Balken von der Untergrenze bis zu ihrem Wert
    fig.add_trace(go.Bar(y=namen, x=[oben - unten] * len(punkte), base=[unten] * len(punkte), orientation="h",
                         marker=dict(color="#eef2f8"), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Bar(y=namen, x=[max(p[1] - unten, (oben - unten) * 0.004) for p in punkte],
                         base=[unten] * len(punkte), orientation="h",
                         marker=dict(color=[HELL if p[2] == "schaetzung" else AKZENT for p in punkte]),
                         text=[("~" if p[2] == "schaetzung" else "") + zahl_text(p[1]) for p in punkte],
                         textposition="outside", cliponaxis=False, showlegend=False,
                         hovertemplate="%{y}: %{text} Mrd USD<extra></extra>"))
    fig.update_layout(**_layout(barmode="overlay", height=90 + 46 * len(punkte), bargap=0.45,
                                xaxis=dict(title="Marktgröße, Mrd USD (Prognosejahr in Klammern)",
                                           range=[unten * 0.9, oben * 1.12], showgrid=True, gridcolor="#eee"),
                                yaxis=dict(automargin=True)))
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False}), ausgelassen


def chart_kette(markt: dict, universum: dict | None, shortlist: set[str]) -> str:
    """Chart 2: Treemap Segmente -> Firmen, Farbe nach Status."""
    import plotly.graph_objects as go
    status = {k["ticker"]: k["status"] for k in (universum or {}).get("kandidaten", []) if "status" in k}
    ids, labels, parents, farben = [], [], [], []
    for seg in markt["segmente"]:
        ids.append(seg["id"]); labels.append(seg["name"]); parents.append(""); farben.append("#f4f6fa")
        for k in seg["kandidaten"]:
            t = k["ticker"]
            if t in shortlist:
                farbe = AKZENT
            elif status.get(t) == "ausgeschlossen":
                farbe = "#e4e4e4"
            else:
                farbe = HELL
            ids.append(f"{seg['id']}/{t}"); labels.append(f"{k['name']}<br><span style='font-size:11px'>{t}</span>")
            parents.append(seg["id"]); farben.append(farbe)
    fig = go.Figure(go.Treemap(ids=ids, labels=labels, parents=parents, marker=dict(colors=farben, line=dict(color="white", width=2)),
                               textfont=dict(family=SCHRIFT), hovertemplate="%{label}<extra></extra>",
                               insidetextfont=dict(color=["#1a1a1a" if f != AKZENT else "white" for f in farben]),
                               tiling=dict(pad=3), pathbar=dict(visible=False)))
    fig.update_layout(**_layout(height=460, margin=dict(l=0, r=0, t=0, b=0)))
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


def chart_streuung(firmen: list[dict]) -> str:
    """Chart 3: Exposure gegen EV/Umsatz, Punktgröße = Marktkapitalisierung."""
    import plotly.graph_objects as go
    punkte = [f for f in firmen if f["exposure"].get("wert") is not None and f["ev_umsatz"] is not None]
    if not punkte:
        return ""
    groessen = [math.sqrt(max(f["mkap_usd"] or 1, 1)) for f in punkte]
    faktor = 46 / max(groessen)
    fig = go.Figure()
    for rolle, farbe in [("Kernprofiteur", AKZENT), ("Zulieferer", MITTEL), ("Mitlaeufer", GRAU)]:
        auswahl = [(f, g) for f, g in zip(punkte, groessen) if f["rolle"] == rolle]
        if not auswahl:
            continue
        fig.add_trace(go.Scatter(
            x=[f["exposure"]["wert"] for f, _ in auswahl], y=[f["ev_umsatz"] for f, _ in auswahl],
            mode="markers+text", name=rolle.replace("ae", "ä"), text=[f["ticker"] for f, _ in auswahl],
            textposition="top center", textfont=dict(size=11),
            marker=dict(size=[max(g * faktor, 9) for _, g in auswahl], color=farbe, opacity=0.85,
                        symbol=["circle-open" if f["exposure"].get("typ") == "schaetzung" else "circle" for f, _ in auswahl],
                        line=dict(width=2, color=farbe)),
            customdata=[[f["name"], zahl_text(f["mkap_usd"] or 0)] for f, _ in auswahl],
            hovertemplate="%{customdata[0]}<br>Exposure %{x} % · EV/Umsatz %{y}x<br>MKap %{customdata[1]} Mrd USD<extra></extra>"))
    fig.update_layout(**_layout(height=440, legend=dict(orientation="h", y=-0.2),
                                xaxis=dict(title="Themen-Exposure, % des Umsatzes (offener Kreis = Schätzung)", range=[0, 105], showgrid=True, gridcolor="#eee"),
                                yaxis=dict(title="EV / Umsatz", showgrid=True, gridcolor="#eee", rangemode="tozero")))
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})


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
    segmente = [{"name": s["name"], "beschreibung": s["beschreibung"], "marge": s["margenprofil"],
                 "groesse": fn.zahl(s["marktgroesse"]) if s.get("marktgroesse") else None,
                 "anzahl": len(s["kandidaten"]),
                 "auswahl": [k["name"] for k in s["kandidaten"] if k["ticker"] in shortlist]}
                for s in markt["segmente"]]
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

    chart1, ausgelassen = chart_spanne(markt)
    from plotly.offline import get_plotlyjs
    return {
        "lauf": lauf_info, "thema": lauf_info.get("thema") or markt["thema"], "datum": lauf_info.get("datum") or markt["datum"],
        "fiktiv": bool(lauf_info.get("fiktiv")), "kopf": kopf, "abschnitte": abschnitte,
        "schaetzungen": schaetzungen, "chart_spanne": Markup(chart1), "chart_ausgelassen": ausgelassen,
        "treiber": punkte(markt["treiber"]), "huerden": punkte(markt["huerden"]),
        "segmente": segmente, "chart_kette": Markup(chart_kette(markt, universum, shortlist)),
        "firmen": firmen, "chart_streuung": Markup(chart_streuung(firmen)),
        "einwaende": einwaende, "redteam": redteam, "bottom_up": bu,
        "beobachtungspunkte": [t(b) for b in report["beobachtungspunkte"]],
        "universum": universum["statistik"] if universum else None,
        "score_formel": universum["regeln"]["score_formel"] if universum else None,
        "gate": tuersteher_statistik(lauf), "fussnoten": fn.liste,
        "gold": GOLD, "mittel": MITTEL,
        "glossar": lektorat.glossar, "lektorat_anzahl": lektorat.anzahl,
        "plotly_js": Markup(get_plotlyjs()), "akzent": AKZENT,
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
