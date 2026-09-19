"""Tests für die Werkzeuge unter tools/ – laufen offline, ohne Agenten und ohne Netz.

Aufruf: python3 -m pytest tests/ -q   (oder bash tests/run_all.sh)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT / "tools"))

import bottom_up  # noqa: E402
import gate  # noqa: E402
import gate_create  # noqa: E402
import kennzahlen  # noqa: E402
import lektorat_vorlage  # noqa: E402
import merge_markt  # noqa: E402
import render  # noqa: E402
import screen  # noqa: E402
import validate  # noqa: E402
from gemeinsam import ToolFehler  # noqa: E402

GUT = PROJEKT / "tests/fixtures/gut"
KAPUTT = PROJEKT / "tests/fixtures/kaputt"
BEISPIEL = PROJEKT / "tests/fixtures/beispiel-lauf"


def lies(pfad: Path) -> dict:
    return json.loads(pfad.read_text(encoding="utf-8"))


def schreib(pfad: Path, daten) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=1), encoding="utf-8")


@pytest.fixture
def beispiel(tmp_path: Path) -> Path:
    """Kopie des fiktiven Beispiel-Laufs, in der Tests gefahrlos ändern dürfen."""
    ziel = tmp_path / "beispiel-lauf"
    shutil.copytree(BEISPIEL, ziel, ignore=shutil.ignore_patterns("*.html", "lektorat-vorlage.json"))
    return ziel


# ---------------------------------------------------------------- validate.py

def test_gute_fixtures_sind_gueltig():
    for datei in sorted(GUT.glob("*.json")):
        fehler, _ = validate.validiere_datei(datei)
        assert fehler == [], f"{datei.name}: {fehler}"


@pytest.mark.parametrize("name, erwartet", [
    ("zahl--ohne-quelle.json", "quelle fehlt (typ=berichtet)"),
    ("zahl--schaetzung-ohne-begruendung.json", "begruendung fehlt (typ=schaetzung)"),
    ("firma--falscher-enum.json", "erlaubt: Kernprofiteur | Zulieferer | Mitlaeufer"),
    ("markt-groesse--zu-wenige-schaetzungen.json", "zu wenige Einträge (2), mindestens 3"),
    ("kette--quelle-und-ticker.json", "kein gültiger yfinance-Ticker"),
])
def test_kaputte_fixtures_melden_den_fehler(name, erwartet):
    fehler, _ = validate.validiere_datei(KAPUTT / name)
    assert any(erwartet in f for f in fehler), fehler


def test_report_verweise_werden_aufgeloest_und_gemeldet():
    fehler, warnungen = validate.validiere_datei(KAPUTT / "report--verweis-kaputt.json")
    gruende = " ".join(fehler)
    assert "Datei fehlt" in gruende
    assert "Index 7 existiert nicht" in gruende
    assert "kein Zahl-Objekt" in gruende
    assert any("ausgeschriebene Zahl" in w for w in warnungen)


def test_schema_aus_dateiname():
    assert validate.schema_fuer_datei(Path("runs/x/firmen/NVDA.json")) == "firma"
    assert validate.schema_fuer_datei(Path("kette--irgendwas.json")) == "kette"
    assert validate.schema_fuer_datei(Path("lauf.json")) is None


def test_lektorat_schuetzt_zahlen_und_felder():
    fehler, warnungen = validate.validiere_datei(KAPUTT / "lektorat/lektorat.json")
    gruende = " ".join(fehler)
    assert "Zahlenverweise verändert" in gruende
    assert "Feld 'ticker' darf nicht umformuliert werden" in gruende
    assert "gehört zu einem Zahl-Objekt" in gruende
    assert "Stelle doppelt ersetzt" in gruende
    assert any("neue ausgeschriebene Zahl" in w for w in warnungen)


def test_json_pointer():
    daten = {"a": [{"b~c": {"d/e": 1}}]}
    assert validate.json_pointer_aufloesen(daten, "/a/0/b~0c/d~1e") == 1
    with pytest.raises(KeyError):
        validate.json_pointer_aufloesen(daten, "/a/5")


# ---------------------------------------------------------------- gate.py / gate_create.py

def test_gate_akzeptiert_gueltige_datei(tmp_path, monkeypatch):
    lauf = tmp_path / "runs/test-2026-01-01"
    lauf.mkdir(parents=True)
    shutil.copy(GUT / "kette.json", lauf / "kette.json")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    code, meldung = gate.pruefen({"task_subject": "[runs/test-2026-01-01/kette.json] Kette", "teammate_name": "kette"})
    assert code == 0 and meldung == ""
    log = [json.loads(z) for z in (lauf / "gate-log.jsonl").read_text().splitlines()]
    assert log[0]["entscheidung"] == "akzeptiert" and log[0]["teammate"] == "kette"


def test_gate_lehnt_kaputte_und_fehlende_datei_ab(tmp_path, monkeypatch):
    lauf = tmp_path / "runs/test-2026-01-01"
    lauf.mkdir(parents=True)
    shutil.copy(KAPUTT / "kette--quelle-und-ticker.json", lauf / "kette.json")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    code, meldung = gate.pruefen({"task_subject": "[runs/test-2026-01-01/kette.json] Kette"})
    assert code == 2 and "Korrigiere die Datei" in meldung
    code, meldung = gate.pruefen({"task_subject": "[runs/test-2026-01-01/treiber.json] Treiber"})
    assert code == 2 and "existiert nicht" in meldung
    assert gate.pruefen({"task_subject": "Koordination: Shortlist"}) == (0, "")
    assert gate.pruefen({"task_subject": "[runs/../geheim.json] x"})[0] == 2


def test_gate_create_erzwingt_konvention():
    assert gate_create.pruefen({"task_subject": "[runs/x-2026-01-01/firmen/NVDA.json] Deep Dive"})[0] == 0
    assert gate_create.pruefen({"task_subject": "Koordination: Shortlist"})[0] == 0
    assert gate_create.pruefen({"task_subject": "Recherchiere den Markt"})[0] == 2


# ---------------------------------------------------------------- kennzahlen.py (ohne Netz)

def _roh(**info):
    basis = {"longName": "Test AG", "currency": "USD", "financialCurrency": "USD", "marketCap": 10e9, "totalRevenue": 2e9,
             "revenueGrowth": 0.1, "grossMargins": 0.4, "operatingMargins": 0.15, "enterpriseToRevenue": 5.0, "trailingPE": 20}
    basis.update(info)
    return {"abgerufen": "2026-01-01", "info": basis}


FX_USD = {"kurs": 1.0, "datum": "2026-01-01", "abgerufen": "2026-01-01"}


def test_kennzahlen_sind_zahl_objekte():
    k = kennzahlen.berechne("TEST", _roh(), FX_USD, FX_USD)
    for name, z in k["kennzahlen"].items():
        assert validate._schema_fehler(z, "zahl") == [], name
    assert k["umsatz_ttm_usd"]["wert"] == 2.0 and k["kennzahlen"]["ev_umsatz"]["wert"] == 5.0


def test_kennzahlen_verwerfen_unplausibles_ev_umsatz():
    zu_klein = kennzahlen.berechne("TEST", _roh(enterpriseToRevenue=1.0), FX_USD, FX_USD)  # MKap/Umsatz = 5
    assert zu_klein["kennzahlen"]["ev_umsatz"]["wert"] is None
    assert "unplausibel" in zu_klein["kennzahlen"]["ev_umsatz"]["hinweis"]
    negativ = kennzahlen.berechne("TEST", _roh(enterpriseToRevenue=-0.9), FX_USD, FX_USD)
    assert negativ["kennzahlen"]["ev_umsatz"]["wert"] is None


def test_kennzahlen_trennen_handels_und_berichtswaehrung():
    fx_chf = {"kurs": 1.2, "datum": "2026-01-01", "abgerufen": "2026-01-01"}
    k = kennzahlen.berechne("ABBN.SW", _roh(currency="CHF", financialCurrency="USD"), fx_chf, FX_USD)
    assert k["waehrung"] == "CHF" and k["berichtswaehrung"] == "USD"
    assert k["marktkapitalisierung_usd"]["wert"] == 12.0 and k["umsatz_ttm_usd"]["wert"] == 2.0
    pence = kennzahlen.berechne("RR.L", _roh(currency="GBp", financialCurrency="GBP"), FX_USD, FX_USD)
    assert pence["waehrung"] == "GBP"


def test_fehlende_werte_bleiben_null():
    k = kennzahlen.berechne("TEST", _roh(trailingPE=None, grossMargins=None), FX_USD, FX_USD)
    assert k["kennzahlen"]["kgv"]["wert"] is None and "hinweis" in k["kennzahlen"]["kgv"]
    assert any("bruttomarge" in h for h in k["hinweise"])


# ---------------------------------------------------------------- merge_markt.py / screen.py / bottom_up.py

def test_merge_markt_fuehrt_zusammen(beispiel):
    markt = merge_markt.zusammenfuehren(beispiel)
    assert len(markt["segmente"]) == 5 and len(markt["schaetzungen"]) == 4
    schreib(beispiel / "markt.json", markt)
    assert validate.validiere_datei(beispiel / "markt.json")[0] == []


def test_merge_markt_bricht_bei_ungueltiger_eingabe_ab(beispiel):
    shutil.copy(KAPUTT / "kette--quelle-und-ticker.json", beispiel / "kette.json")
    with pytest.raises(ToolFehler):
        merge_markt.zusammenfuehren(beispiel)


def test_screen_kandidaten_und_duplikate():
    markt = lies(BEISPIEL / "markt.json")
    markt["segmente"][1]["kandidaten"].append({"name": "Doppelt", "ticker": markt["segmente"][0]["kandidaten"][0]["ticker"], "begruendung": "x"})
    liste = screen.kandidaten_sammeln(markt)
    duplikate = [e for e in liste if e.get("status") == "ausgeschlossen"]
    assert len(duplikate) == 1 and "Duplikat" in duplikate[0]["grund"]


def test_screen_score_und_shortlist_rundlauf():
    assert screen.perzentilrang([1, 2, 3, 4], 4) == 1.0 and screen.perzentilrang([1, 2, 3, 4], 1) == 0.0
    regeln = lies(PROJEKT / "tools/screen_regeln.json")["score"]
    aufgenommen = [
        {"ticker": "A", "name": "A", "segment_id": "s1", "kennzahlen": {"umsatzwachstum_yoy": 30, "operative_marge": 20, "ev_umsatz": 10}},
        {"ticker": "B", "name": "B", "segment_id": "s1", "kennzahlen": {"umsatzwachstum_yoy": 20, "operative_marge": 15, "ev_umsatz": 5}},
        {"ticker": "C", "name": "C", "segment_id": "s2", "kennzahlen": {"umsatzwachstum_yoy": 5, "operative_marge": 5, "ev_umsatz": None}},
    ]
    screen.scores_berechnen(aufgenommen, regeln)
    assert all(0 <= e["score"] <= 100 for e in aufgenommen)
    assert any("ev_umsatz fehlt" in h for h in aufgenommen[2]["hinweise"])
    vorschlag = screen.shortlist_vorschlagen(aufgenommen, 2)
    assert {v["segment_id"] for v in vorschlag} == {"s1", "s2"}, "jedes Segment kommt vor dem zweiten Platz dran"


def test_bottom_up_rechnet_und_kennzeichnet(beispiel):
    ergebnis = bottom_up.berechnen(beispiel)
    assert ergebnis["summe_themenumsatz"]["typ"] == "schaetzung"
    assert len(ergebnis["firmen"]) == 6
    assert any("EUR" in h for h in ergebnis["hinweise"]), "EUR-Schätzung wird übersprungen, nicht umgerechnet"
    assert bottom_up.in_mrd_usd({"wert": 150000, "einheit": "Mio USD"}) == 150.0
    assert bottom_up.in_mrd_usd({"wert": 1, "einheit": "Mrd EUR"}) is None


# ---------------------------------------------------------------- lektorat_vorlage.py / render.py

def test_lektorat_vorlage_sammelt_sichtbare_texte(beispiel):
    texte = lektorat_vorlage.vorlage(beispiel)
    pfade = {(t["datei"], t["pfad"]) for t in texte}
    assert ("report.json", "/these") in pfade
    assert ("firmen/BRAG.FIKTIV.json", "/bull_case/0") in pfade
    assert ("redteam.json", "/gesamturteil") in pfade
    assert all(isinstance(t["original"], str) for t in texte)


def test_render_erzeugt_report_mit_exhibits_und_lektorat(beispiel):
    ziel = render.rendern(beispiel)
    html = ziel.read_text(encoding="utf-8")
    for erwartet in ("Exhibit 1", "Exhibit 2", "Exhibit 3", "Exhibit 4", 'svg class="streuung"', "Begriffe kurz erklärt",
                     "Fiktives Beispiel", "Keine Anlageberatung", "Textstellen sprachlich"):
        assert erwartet in html, erwartet
    assert "{ref:" not in html, "alle Verweise aufgelöst"
    assert "plotly" not in html.lower()
    assert ziel.stat().st_size < 1_000_000
    ohne = render.rendern(beispiel, mit_lektorat=False)
    assert "Begriffe kurz erklärt" not in ohne.read_text(encoding="utf-8")


def test_render_prueft_alle_dateien_des_laufs(beispiel):
    shutil.copy(KAPUTT / "kette--quelle-und-ticker.json", beispiel / "kette.json")
    with pytest.raises(ToolFehler, match="kette.json"):
        render.rendern(beispiel)


def test_tuersteher_statistik_zaehlt_aufgaben_einmal(beispiel):
    log = beispiel / "gate-log.jsonl"
    eintraege = [json.loads(z) for z in log.read_text().splitlines()]
    eintraege.append({**eintraege[-1]})  # doppeltes TaskCompleted für dieselbe Aufgabe
    log.write_text("".join(json.dumps(e) + "\n" for e in eintraege))
    stat = render.tuersteher_statistik(beispiel)
    assert stat["pruefungen"] == len(eintraege)
    assert stat["aufgaben"] == len({e.get("task_id") or e["datei"] for e in eintraege})


def test_zahlformat():
    assert render.zahl_text(214.6) == "215"
    assert render.zahl_text(84.7) == "84,7"
    assert render.zahl_text(0.5) == "0,50"
    assert render.zahl_text(0) == "0"
    assert render.formatiere({"wert": 30, "einheit": "% Umsatz", "typ": "schaetzung"}) == "~30 %"
    assert render.kurzname("Shenzhen Inovance Technology") == "Inovance"
    assert render._runde_skala(214.6)[-1] == 250
