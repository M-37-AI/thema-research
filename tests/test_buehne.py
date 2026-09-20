"""Tests für die Bühne (tools/buehne_modell.py, tools/buehne.py) – offline, ohne Agenten.

Aufruf: python3 -m pytest tests/test_buehne.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJEKT / "tools"))

import buehne_modell as bm  # noqa: E402

FIX = PROJEKT / "tests/fixtures/transkripte"
FIX_PROJEKT = Path("/tmp/projekt")          # cwd in den Fixtures
ROLLEN = {"markt", "treiber", "kette", "firma", "red-team", "lektor"}


def zeilen(name: str) -> list[dict]:
    return [json.loads(z) for z in (FIX / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if z.strip()]


@pytest.fixture
def preise() -> dict:
    return bm.lade_preise()


# ---------------------------------------------------------------- Task 1: Preise, Rollen, Kosten
def test_preis_fuer_schneidet_datumssuffix(preise):
    assert bm.preis_fuer("claude-sonnet-5", preise)["output"] == 10
    assert bm.preis_fuer("claude-sonnet-5-20260101", preise)["output"] == 10
    assert bm.preis_fuer("claude-unbekannt-9", preise) is None


def test_kosten_bekanntes_modell(preise):
    usage = {"input_tokens": 2, "output_tokens": 100, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 17509,
             "cache_creation": {"ephemeral_5m_input_tokens": 1909, "ephemeral_1h_input_tokens": 15600}}
    betrag, unbekannt = bm.kosten_usd(usage, "claude-sonnet-5", preise)
    assert unbekannt is False
    assert betrag == pytest.approx(0.0681765, abs=1e-9)


def test_kosten_ohne_cache_aufschluesselung_zaehlt_als_5m(preise):
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 1_000_000}
    betrag, _ = bm.kosten_usd(usage, "claude-opus-5", preise)
    assert betrag == pytest.approx(0.5 + 6.25)


def test_kosten_unbekanntes_modell_null_und_flag(preise):
    betrag, unbekannt = bm.kosten_usd({"input_tokens": 5, "output_tokens": 5}, "claude-xyz", preise)
    assert betrag == 0 and unbekannt is True


@pytest.mark.parametrize("name,erwartet", [
    ("firma-3-2", "firma"), ("red-team-bio", "red-team"), ("markt-2", "markt"), ("lead", "lead"),
    ("lektor", "lektor"), ("unbekannt-1", "sonstige"), ("firma", "firma"),
])
def test_rolle_aus_name(name, erwartet):
    assert bm.rolle_aus_name(name, ROLLEN) == erwartet


def test_modell_kurz():
    assert bm.modell_kurz("claude-sonnet-5") == "Sonnet 5"
    assert bm.modell_kurz("claude-fable-5-1") == "Fable 5.1"
    assert bm.modell_kurz("claude-haiku-4-5-20251001") == "Haiku 4.5"
    assert bm.modell_kurz("") == "?"


# ---------------------------------------------------------------- Task 2: Zeile → Ereignisse
def test_agent_aus_zeile():
    assert bm.agent_aus_zeile(zeilen("lead")[0]) == "lead"
    assert bm.agent_aus_zeile(zeilen("markt")[0]) == "markt"


def test_text_und_verbrauch(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("lead")[1], "lead", FIX_PROJEKT, preise)
    arten = [e["art"] for e in ev]
    assert arten == ["text", "verbrauch"]
    assert ev[0]["text"].startswith("Ich lege den Lauf-Ordner an")
    assert ev[0]["agent"] == "lead" and ev[0]["zeit"] == "2026-09-20T08:00:05.000Z"
    v = ev[1]
    assert v["modell"] == "claude-fable-5-1" and v["output"] == 40 and v["cache_lesen"] == 12000
    assert v["cache_schreiben_1h"] == 500 and v["cache_schreiben_5m"] == 0
    assert v["kosten_usd"] == pytest.approx(3 * 10e-6 + 40 * 50e-6 + 12000 * 0.25e-6 + 500 * 20e-6)


def test_denkt_ohne_inhalt(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("markt")[1], "markt", FIX_PROJEKT, preise)
    assert ev[0]["art"] == "denkt" and "text" not in ev[0]


def test_werkzeug_websearch(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("markt")[2], "markt", FIX_PROJEKT, preise)[0]
    assert ev["art"] == "werkzeug" and ev["werkzeug"] == "WebSearch"
    assert ev["titel"] == "Sucht: Testthema Marktgröße 2030 Prognose"
    assert ev["tool_use_id"] == "toolu_m1"


def test_werkzeug_wiretoolinputs_hat_vorrang(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("markt")[4], "markt", FIX_PROJEKT, preise)[0]
    assert ev["werkzeug"] == "Bash"
    assert ev["titel"] == "Führt aus: Datei validieren"
    assert ev["detail"] == "python3 tools/validate.py runs/testthema-2026-09-20/markt-groesse.json"


def test_werkzeug_taskupdate_completed(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("markt")[6], "markt", FIX_PROJEKT, preise)[0]
    assert ev["titel"] == "Meldet fertig: #1" and ev["fertig_gemeldet"] is True


def test_ergebnis(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("markt")[3], "markt", FIX_PROJEKT, preise)
    assert len(ev) == 1 and ev[0]["art"] == "ergebnis" and ev[0]["tool_use_id"] == "toolu_m1"
    assert ev[0]["fehler"] is False and ev[0]["auszug"].startswith("Web search results")
    fehler = bm.ereignisse_aus_zeile(zeilen("firma-1")[4], "firma-1", FIX_PROJEKT, preise)[0]
    assert fehler["fehler"] is True


def test_nachricht_mit_aufgabe(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("markt")[0], "markt", FIX_PROJEKT, preise)[0]
    assert ev["art"] == "nachricht" and ev["von"] == "team-lead"
    assert ev["aufgabe"] == "[runs/testthema-2026-09-20/markt-groesse.json] Marktgröße"
    zuweisung = bm.ereignisse_aus_zeile(zeilen("firma-1")[0], "firma-1", FIX_PROJEKT, preise)[0]
    assert zuweisung["aufgabe"] == "[runs/testthema-2026-09-20/firmen/NVDA.json] Deep Dive NVIDIA"
    assert zuweisung["text"].startswith("Aufgabe #4")
    ende = bm.ereignisse_aus_zeile(zeilen("firma-1")[10], "firma-1", FIX_PROJEKT, preise)[0]
    assert ende["beenden"] is True


def test_tuersteher_rueckmeldung(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("firma-1")[5], "firma-1", FIX_PROJEKT, preise)[0]
    assert ev["art"] == "tuersteher_rueckmeldung"
    assert ev["text"].startswith("Türsteher: 2 Fehler")
    assert len(ev["text"]) <= bm.MAX_NACHRICHT


def test_write_pfad_relativ(preise):
    ev = bm.ereignisse_aus_zeile(zeilen("firma-1")[1], "firma-1", FIX_PROJEKT, preise)[0]
    assert ev["titel"] == "Schreibt: runs/testthema-2026-09-20/firmen/NVDA.json"


def test_ignorierte_zeilen(preise):
    assert bm.ereignisse_aus_zeile(zeilen("lead")[5], "lead", FIX_PROJEKT, preise) == []
    assert bm.ereignisse_aus_zeile(zeilen("markt")[9], "markt", FIX_PROJEKT, preise) == []
    assert bm.ereignisse_aus_zeile(zeilen("lead")[0], "lead", FIX_PROJEKT, preise) == []   # nackter Prompt des Nutzers


def test_kuerzung(preise):
    zeile = {"type": "assistant", "timestamp": "2026-09-20T08:00:00Z",
             "message": {"model": "claude-sonnet-5", "content": [{"type": "text", "text": "x" * 2000}]}}
    ev = bm.ereignisse_aus_zeile(zeile, "markt", FIX_PROJEKT, preise)[0]
    assert len(ev["text"]) <= bm.MAX_TEXT + 1


@pytest.mark.parametrize("name,eingabe,titel", [
    ("Read", {"file_path": "/tmp/projekt/schemas/firma.schema.json"}, "Liest: schemas/firma.schema.json"),
    ("Edit", {"file_path": "/tmp/projekt/runs/x/kette.json"}, "Schreibt: runs/x/kette.json"),
    ("WebFetch", {"url": "https://www.example.org/studie/2030?x=1"}, "Liest: www.example.org/studie/2030"),
    ("TaskUpdate", {"taskId": "7", "status": "in_progress"}, "Aufgabe #7: in_progress"),
    ("TaskList", {}, "Schaut in die Aufgabenliste"),
    ("SendMessage", {"to": "firma-2", "message": "hallo"}, "Schreibt an firma-2"),
    ("Agent", {"name": "kette", "subagent_type": "kette"}, "Startet kette (kette)"),
    ("TaskCreate", {"subject": "[runs/x/report.json] Report"}, "Legt Aufgabe an: [runs/x/report.json] Report"),
    ("Grep", {"pattern": "ticker"}, "Sucht in Dateien: ticker"),
    ("Unbekannt", {"a": 1}, "Unbekannt"),
])
def test_werkzeug_titel(name, eingabe, titel):
    assert bm.werkzeug_titel(name, eingabe, FIX_PROJEKT)[0] == titel


def test_ereignis_aus_gate():
    g = zeilen("gate-log")[1]
    ev = bm.ereignis_aus_gate(g)
    assert ev["art"] == "tuersteher" and ev["agent"] == "firma-1" and ev["entscheidung"] == "abgelehnt"
    assert ev["datei"] == "runs/testthema-2026-09-20/firmen/NVDA.json" and len(ev["fehler"]) == 2
    assert ev["zeit"] == "2026-09-20T10:05:41+02:00"


def test_zeit_epoch():
    assert bm.zeit_epoch("2026-09-20T08:05:41+02:00") == bm.zeit_epoch("2026-09-20T06:05:41.000Z")
    assert bm.zeit_epoch("kaputt") == 0.0


# ---------------------------------------------------------------- Task 3: Team, Karten, Phase
def alle_ereignisse(preise, *namen):
    evs = []
    for n in namen:
        for z in zeilen(n):
            evs += bm.ereignisse_aus_zeile(z, bm.agent_aus_zeile(z), FIX_PROJEKT, preise)
    return evs


def neues_team(preise, lauf: Path, uhr=None):
    return bm.Team(lauf, FIX_PROJEKT, preise, ROLLEN, uhr=uhr or (lambda: 0.0))


def test_zustandsfolge(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    evs = alle_ereignisse(preise, "markt")
    folge = []
    for ev in evs:
        team.verarbeite(ev)
        folge.append(team.karte("markt")["zustand"])
    # 0 nachricht, 1 denkt, 2 verbrauch, 3 werkzeug, 4 verbrauch, 5 ergebnis, 6 werkzeug, 7 verbrauch, 8 ergebnis,
    # 9 werkzeug TaskUpdate completed, 10 verbrauch, 11 ergebnis (ok), 12 text, 13 verbrauch
    assert folge[0] == "bereit"
    assert folge[1] == "denkt"
    assert folge[3] == "werkzeug"
    assert folge[5] == "werkzeug"          # Ergebnis ändert den Zustand nicht
    assert folge[9] == "wartet_tuersteher"
    assert folge[11] == "bereit"           # Fertigmeldung ging durch (Ergebnis ohne Fehler)
    k = team.karte("markt")
    assert k["zustand"] == "schreibt"
    assert k["aufgabe"] == "[runs/testthema-2026-09-20/markt-groesse.json] Marktgröße"
    assert k["modell"] == "claude-sonnet-5" and k["modell_kurz"] == "Sonnet 5"
    assert k["rolle"] == "markt" and k["schritte"] == 3       # Werkzeugaufrufe: WebSearch, Bash, TaskUpdate
    assert len(k["strom"]) == 9


def test_tuersteher_beendet_warten_und_zaehlt(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    for ev in alle_ereignisse(preise, "markt"):
        team.verarbeite(ev)
    aus = team.verarbeite(bm.ereignis_aus_gate(zeilen("gate-log")[0]))
    k = team.karte("markt")
    assert k["zustand"] == "bereit"
    assert k["tuersteher"] == {"akzeptiert": 1, "abgelehnt": 0, "letzte": aus[0][1]} or k["tuersteher"]["akzeptiert"] == 1
    assert team.snapshot()["tuersteher"] == {"akzeptiert": 1, "abgelehnt": 0}
    arten = [a for a, _ in aus]
    assert "ereignis" in arten and "karte" in arten and "lauf" in arten


def test_ablehnung_setzt_korrigiert_und_lead_wird_umgeleitet(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    evs = alle_ereignisse(preise, "firma-1")
    for ev in evs[:5]:      # bis einschließlich TaskUpdate completed
        team.verarbeite(ev)
    assert team.karte("firma-1")["zustand"] == "wartet_tuersteher"
    team.verarbeite(bm.ereignis_aus_gate(zeilen("gate-log")[1]))
    assert team.karte("firma-1")["zustand"] == "korrigiert"
    assert team.karte("firma-1")["tuersteher"]["abgelehnt"] == 1
    for ev in evs[5:10]:
        team.verarbeite(ev)
    # Dritte Zeile im Gate-Log steht auf "lead", gehört aber zur Aufgabe von firma-1
    aus = team.verarbeite(bm.ereignis_aus_gate(zeilen("gate-log")[2]))
    assert team.karte("firma-1")["tuersteher"]["akzeptiert"] == 1
    assert "lead" not in team.snapshot()["agenten"]
    assert [p["agent"] for a, p in aus if a == "ereignis"] == ["firma-1"]


def test_beenden_setzt_fertig(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    for ev in alle_ereignisse(preise, "firma-1"):
        team.verarbeite(ev)
    assert team.karte("firma-1")["zustand"] == "fertig"


def test_untaetig_und_fertig_per_uhr(preise, tmp_path):
    jetzt = {"t": bm.zeit_epoch("2026-09-20T08:01:08.000Z")}
    team = neues_team(preise, tmp_path, uhr=lambda: jetzt["t"])
    for ev in alle_ereignisse(preise, "markt"):
        team.verarbeite(ev)
    team.verarbeite(bm.ereignis_aus_gate(zeilen("gate-log")[0]))
    assert team.tick() == [] or team.karte("markt")["zustand"] == "bereit"
    jetzt["t"] += bm.UNTAETIG_S + 1
    aus = team.tick()
    assert team.karte("markt")["zustand"] == "untaetig"
    assert any(a == "karte" for a, _ in aus)
    jetzt["t"] += bm.FERTIG_S
    team.tick()
    assert team.karte("markt")["zustand"] == "fertig"


def test_kosten_summieren_sich(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    for ev in alle_ereignisse(preise, "lead", "markt"):
        team.verarbeite(ev)
    lead, markt = team.karte("lead"), team.karte("markt")
    assert lead["tokens"]["output"] == 190 and markt["tokens"]["output"] == 250
    assert markt["tokens"]["cache_schreiben"] == 17809
    erwartet_markt = sum(e["kosten_usd"] for e in alle_ereignisse(preise, "markt") if e["art"] == "verbrauch")
    assert markt["kosten_usd"] == pytest.approx(erwartet_markt)
    snap = team.snapshot()
    assert snap["kosten_usd"] == pytest.approx(lead["kosten_usd"] + markt["kosten_usd"])
    assert snap["tokens"]["output"] == 440


def test_reihenfolge_und_snapshot(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    for ev in alle_ereignisse(preise, "firma-1", "markt", "lead"):
        team.verarbeite(ev)
    snap = team.snapshot()
    json.dumps(snap)      # serialisierbar
    assert snap["reihenfolge"] == ["lead", "markt", "firma-1"]
    for feld in ("lauf", "phase", "phasen", "laufzeit_s", "kosten_usd", "tokens", "tuersteher", "agenten",
                 "reihenfolge", "modus", "erwartet"):
        assert feld in snap
    assert snap["phasen"] == bm.PHASEN
    assert snap["erwartet"] == ["markt", "treiber", "kette", "firma", "firma", "firma", "firma", "red-team", "lektor"]
    assert snap["agenten"]["lead"]["rolle"] == "lead"
    assert len(snap["agenten"]["markt"]["strom"]) == 9


def test_strom_begrenzt(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    for i in range(bm.MAX_STROM + 10):
        team.verarbeite({"zeit": f"2026-09-20T08:00:{i % 60:02d}Z", "agent": "kette", "art": "text", "text": str(i)})
    assert len(team.karte("kette")["strom"]) == bm.MAX_STROM
    assert team.karte("kette")["strom"][-1]["text"] == str(bm.MAX_STROM + 9)


def test_phase_bestimmen(tmp_path):
    assert bm.phase_bestimmen(tmp_path, set()) == "Phase 1"
    (tmp_path / "markt-groesse.json").write_text("{}")
    assert bm.phase_bestimmen(tmp_path, {"markt-groesse.json"}) == "Phase 1"
    assert bm.phase_bestimmen(tmp_path, {"markt-groesse.json", "treiber.json", "kette.json"}) == "Screening"
    (tmp_path / "shortlist.json").write_text(json.dumps({"auswahl": [{"ticker": "AAA"}, {"ticker": "BBB"}]}))
    assert bm.phase_bestimmen(tmp_path, {"markt-groesse.json", "treiber.json", "kette.json"}) == "Deep Dives"
    p1 = {"markt-groesse.json", "treiber.json", "kette.json", "firmen/AAA.json"}
    assert bm.phase_bestimmen(tmp_path, p1) == "Deep Dives"
    p1.add("firmen/BBB.json")
    assert bm.phase_bestimmen(tmp_path, p1) == "Red Team"
    p1.add("redteam.json")
    assert bm.phase_bestimmen(tmp_path, p1) == "Report"
    p1.add("report.json")
    assert bm.phase_bestimmen(tmp_path, p1) == "Lektorat"
    (tmp_path / "report.html").write_text("<html>")
    assert bm.phase_bestimmen(tmp_path, p1) == "Fertig"


def test_phase_beispiel_lauf():
    lauf = PROJEKT / "tests/fixtures/beispiel-lauf"
    assert bm.phase_bestimmen(lauf, set()) == "Fertig"


def test_phase_im_team_aus_gate_log(preise, tmp_path):
    team = neues_team(preise, tmp_path)
    for name in ("markt-groesse.json", "treiber.json", "kette.json"):
        team.verarbeite({"zeit": "2026-09-20T10:00:00+02:00", "agent": "markt", "art": "tuersteher",
                         "entscheidung": "akzeptiert", "datei": f"runs/x/{name}", "grund": "gültig", "fehler": []})
    assert team.snapshot()["phase"] == "Screening"


# ---------------------------------------------------------------- Task 4/5: Server-Seite (tools/buehne.py)
import os  # noqa: E402
import threading  # noqa: E402
import urllib.request  # noqa: E402

import buehne  # noqa: E402


def test_projekt_slug():
    assert buehne.projekt_slug(Path("/Users/x/KI Praxis/thema-research")) == "-Users-x-KI-Praxis-thema-research"


def projekt_mit_transkripten(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """Ein leeres Projekt plus Transkript-Ordner unter CLAUDE_CONFIG_DIR mit den drei Fixtures."""
    projekt = tmp_path / "projekt"
    (projekt / "runs" / "testthema-2026-09-20").mkdir(parents=True)
    konfig = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(konfig))
    ordner = konfig / "projects" / buehne.projekt_slug(projekt)
    ordner.mkdir(parents=True)
    for name, sid in (("lead", "lead0000-0000-0000-0000-000000000001"), ("markt", "aaaa0000-0000-0000-0000-000000000002"),
                      ("firma-1", "bbbb0000-0000-0000-0000-000000000003")):
        text = (FIX / f"{name}.jsonl").read_text(encoding="utf-8").replace("/tmp/projekt", str(projekt))
        (ordner / f"{sid}.jsonl").write_text(text, encoding="utf-8")
    return projekt, ordner


def test_transkript_ordner_ehrt_config_dir(tmp_path, monkeypatch):
    projekt, ordner = projekt_mit_transkripten(tmp_path, monkeypatch)
    assert buehne.transkript_ordner(projekt) == ordner


def test_finde_lead_und_teammates(tmp_path, monkeypatch):
    projekt, ordner = projekt_mit_transkripten(tmp_path, monkeypatch)
    lead = buehne.finde_lead(ordner, projekt, lead_id=None, nach=None)
    assert lead is not None and lead.name.startswith("lead0000")
    assert buehne.session_id(lead) == "lead0000-0000-0000-0000-000000000001"
    mates = buehne.finde_teammates(ordner, "lead0000-0000-0000-0000-000000000001")
    assert sorted(p.name[:4] for p in mates) == ["aaaa", "bbbb"]
    assert buehne.finde_lead(ordner, projekt, lead_id="lead0000-0000-0000-0000-000000000001", nach=None) == lead
    assert buehne.finde_lead(ordner, projekt, lead_id="gibtsnicht", nach=None) is None
    # 'nach' filtert nach Zeitstempel der ersten Zeile
    assert buehne.finde_lead(ordner, projekt, lead_id=None, nach="2026-09-20T09:00:00Z") is None
    assert buehne.finde_lead(ordner, projekt, lead_id=None, nach="2026-09-20T07:00:00Z") == lead


def test_finde_lead_ignoriert_fremdes_cwd(tmp_path, monkeypatch):
    projekt, ordner = projekt_mit_transkripten(tmp_path, monkeypatch)
    fremd = ordner / "cccc0000-0000-0000-0000-000000000009.jsonl"
    fremd.write_text(json.dumps({"type": "user", "sessionId": "cccc", "cwd": "/anderswo",
                                 "timestamp": "2026-09-20T09:00:00.000Z", "message": {"role": "user", "content": "x"}}) + "\n")
    lead = buehne.finde_lead(ordner, projekt, lead_id=None, nach=None)
    assert lead.name.startswith("lead0000")


def test_tailer_liest_nur_ganze_zeilen(tmp_path):
    pfad = tmp_path / "t.jsonl"
    pfad.write_text('{"a": 1}\n{"a": 2')
    t = buehne.Tailer(pfad)
    assert [z["a"] for z in t.lies()] == [1]
    with pfad.open("a") as f:
        f.write('}\n{"a": 3}\nkaputt\n')
    assert [z["a"] for z in t.lies()] == [2, 3]
    assert t.lies() == []
    pfad.write_text('{"a": 9}\n')          # Datei wurde gekürzt → von vorn
    assert [z["a"] for z in t.lies()] == [9]


def test_replay_ereignisse_sortiert(tmp_path, monkeypatch, preise):
    projekt, ordner = projekt_mit_transkripten(tmp_path, monkeypatch)
    gate = projekt / "runs" / "testthema-2026-09-20" / "gate-log.jsonl"
    gate.write_text((FIX / "gate-log.jsonl").read_text(encoding="utf-8"))
    evs = buehne.replay_ereignisse(sorted(ordner.glob("*.jsonl")), gate, projekt, preise)
    zeiten = [bm.zeit_epoch(e["zeit"]) for e in evs]
    assert zeiten == sorted(zeiten)
    assert sum(e["art"] == "tuersteher" for e in evs) == 3
    assert {e["agent"] for e in evs} >= {"lead", "markt", "firma-1"}


def test_server_smoke(tmp_path, monkeypatch, preise):
    projekt, ordner = projekt_mit_transkripten(tmp_path, monkeypatch)
    lauf = projekt / "runs" / "testthema-2026-09-20"
    (lauf / "gate-log.jsonl").write_text((FIX / "gate-log.jsonl").read_text(encoding="utf-8"))
    (lauf / "lauf.json").write_text(json.dumps({"thema": "Testthema", "slug": "testthema", "datum": "2026-09-20",
                                                "gestartet": "2026-09-20T10:00:00+02:00"}))
    server = buehne.starte_server(lauf, projekt, port=0, replay=True, speed=1000.0, lead_id=None)
    try:
        port = server.server_address[1]
        for _ in range(50):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
                snap = json.loads(r.read())
            if snap["modus"] == "replay-ende":
                break
            import time as _t
            _t.sleep(0.05)
        assert snap["modus"] == "replay-ende"
        assert set(snap["agenten"]) == {"lead", "markt", "firma-1"}
        assert snap["tuersteher"] == {"akzeptiert": 2, "abgelehnt": 1}
        assert snap["lauf"]["thema"] == "Testthema"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
            assert r.status == 200 and b"<title>" in r.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/gibtsnicht", timeout=2) as r:
            pass
    except urllib.error.HTTPError as e:
        assert e.code == 404
    finally:
        server.shutdown()
