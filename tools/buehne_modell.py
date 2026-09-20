"""Modell der Bühne: reine Funktionen ohne Netz und ohne Threads.

Wandelt Transkriptzeilen (~/.claude/projects/…/<session>.jsonl) und Zeilen des
Türsteher-Logs (runs/<lauf>/gate-log.jsonl) in Ereignisse um und führt daraus
den Zustand je Agenten-Karte und den Gesamtzustand des Laufs. Der Server
(tools/buehne.py) liest Dateien und verteilt; hier wird nur gerechnet.

Ereignis: {"zeit": ISO, "agent": Name, "art": …, …}   (Arten siehe ARTEN)
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HIER = Path(__file__).resolve().parent
PREISE_DATEI = HIER / "preise.json"

MAX_TEXT = 600          # Zeichen je Textausgabe im Strom
MAX_DETAIL = 200        # Zeichen je Werkzeug-Detail und Ergebnis-Auszug
MAX_NACHRICHT = 300     # Zeichen je Teammate-Nachricht / Türsteher-Rückmeldung
MAX_STROM = 40          # Ereignisse je Karte im Speicher
MAX_FEHLER = 5          # Fehlerzeilen je Türsteher-Ereignis
UNTAETIG_S = 90         # Sekunden ohne Ereignis → untätig
FERTIG_S = 600          # Sekunden ohne Ereignis → fertig

ARTEN = ("text", "denkt", "werkzeug", "ergebnis", "nachricht", "tuersteher_rueckmeldung", "verbrauch", "tuersteher")
STROM_ARTEN = ("text", "denkt", "werkzeug", "ergebnis", "nachricht", "tuersteher_rueckmeldung", "tuersteher")

ROLLEN_REIHENFOLGE = ["lead", "markt", "treiber", "kette", "firma", "red-team", "lektor", "sonstige"]
ERWARTET = ["markt", "treiber", "kette", "firma", "firma", "firma", "firma", "red-team", "lektor"]
PHASEN = ["Phase 1", "Screening", "Deep Dives", "Red Team", "Report", "Lektorat", "Fertig"]
PHASE_1_DATEIEN = {"markt-groesse.json", "treiber.json", "kette.json"}

TEAMMATE_NACHRICHT = re.compile(r'<teammate-message\s+teammate_id="([^"]+)"[^>]*>(.*?)</teammate-message>', re.S)
AUFGABE_MUSTER = re.compile(r"(\[runs/[^\]]+\.json\][^\n.]*)")
RUECKMELDUNG_PRAEFIX = "TaskCompleted hook feedback:"
DATUMSSUFFIX = re.compile(r"-\d{8}$")


# ---------------------------------------------------------------- Preise, Modelle, Rollen
def lade_preise(pfad: Path | None = None) -> dict[str, dict]:
    daten = json.loads((pfad or PREISE_DATEI).read_text(encoding="utf-8"))
    return {k: v for k, v in daten.items() if not k.startswith("_")}


def preis_fuer(modell_id: str, preise: dict) -> dict | None:
    if not modell_id:
        return None
    if modell_id in preise:
        return preise[modell_id]
    kurz = DATUMSSUFFIX.sub("", modell_id)
    if kurz in preise:
        return preise[kurz]
    treffer = [k for k in preise if kurz.startswith(k + "-")]
    return preise[max(treffer, key=len)] if treffer else None


def kosten_usd(usage: dict, modell_id: str, preise: dict) -> tuple[float, bool]:
    """(Betrag in USD, preis_unbekannt). Cache-Schreiben ohne Aufschlüsselung zählt als 5-Minuten-Cache."""
    p = preis_fuer(modell_id, preise)
    if p is None:
        return 0.0, True
    usage = usage or {}
    cc = usage.get("cache_creation") or {}
    schreiben_gesamt = usage.get("cache_creation_input_tokens") or 0
    s1h = cc.get("ephemeral_1h_input_tokens")
    s5m = cc.get("ephemeral_5m_input_tokens")
    if s1h is None and s5m is None:
        s5m, s1h = schreiben_gesamt, 0
    betrag = ((usage.get("input_tokens") or 0) * p["input"]
              + (usage.get("output_tokens") or 0) * p["output"]
              + (usage.get("cache_read_input_tokens") or 0) * p["cache_lesen"]
              + (s5m or 0) * p["cache_schreiben_5m"]
              + (s1h or 0) * p["cache_schreiben_1h"]) / 1_000_000
    return betrag, False


def modell_kurz(modell_id: str) -> str:
    if not modell_id:
        return "?"
    teile = DATUMSSUFFIX.sub("", modell_id).removeprefix("claude-").split("-")
    name = teile[0].capitalize()
    version = ".".join(t for t in teile[1:] if t.isdigit())
    return f"{name} {version}".strip()


def rolle_aus_name(name: str, rollen: set[str]) -> str:
    if name == "lead":
        return "lead"
    treffer = [r for r in rollen if name == r or name.startswith(r + "-")]
    return max(treffer, key=len) if treffer else "sonstige"


def zeit_epoch(zeit: str) -> float:
    try:
        d = datetime.fromisoformat(zeit.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


# ---------------------------------------------------------------- Zeile → Ereignisse
def _kurz(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def _relativ(pfad: str, projekt: Path) -> str:
    praefix = str(projekt).rstrip("/") + "/"
    return pfad[len(praefix):] if pfad.startswith(praefix) else pfad


def _ergebnis_text(inhalt) -> str:
    if isinstance(inhalt, str):
        return inhalt
    if isinstance(inhalt, list):
        return "\n".join(b.get("text", "") for b in inhalt if isinstance(b, dict) and b.get("type") == "text")
    return ""


def agent_aus_zeile(zeile: dict) -> str:
    return zeile.get("agentName") or "lead"


def werkzeug_titel(name: str, eingabe: dict, projekt: Path) -> tuple[str, str]:
    """Klartext-Titel und Detail für einen Werkzeugaufruf."""
    e = eingabe or {}
    pfad = _relativ(e.get("file_path") or e.get("notebook_path") or "", projekt)
    if name == "WebSearch":
        return f"Sucht: {e.get('query', '')}", _kurz(e.get("query", ""), MAX_DETAIL)
    if name == "WebFetch":
        u = urlparse(e.get("url", ""))
        return f"Liest: {u.netloc}{_kurz(u.path, 60)}", _kurz(e.get("url", ""), MAX_DETAIL)
    if name == "Read":
        return f"Liest: {pfad}", pfad
    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return f"Schreibt: {pfad}", pfad
    if name == "Bash":
        befehl = e.get("command", "") or ""
        erste = befehl.splitlines()[0] if befehl else ""
        return f"Führt aus: {e.get('description') or _kurz(erste, 80)}", _kurz(befehl, MAX_DETAIL)
    if name == "TaskUpdate":
        nr, status = e.get("taskId", "?"), e.get("status")
        if status == "completed":
            return f"Meldet fertig: #{nr}", _kurz(json.dumps(e, ensure_ascii=False), MAX_DETAIL)
        return (f"Aufgabe #{nr}: {status}" if status else f"Aufgabe #{nr}"), _kurz(json.dumps(e, ensure_ascii=False), MAX_DETAIL)
    if name in ("TaskList", "TaskGet"):
        return "Schaut in die Aufgabenliste", ""
    if name == "TaskCreate":
        return f"Legt Aufgabe an: {e.get('subject', '')}", _kurz(e.get("description", ""), MAX_DETAIL)
    if name == "SendMessage":
        return f"Schreibt an {e.get('to') or e.get('recipient') or '?'}", _kurz(e.get("message", ""), MAX_DETAIL)
    if name in ("Agent", "Task"):
        wer = e.get("name") or e.get("description") or "Subagent"
        typ = e.get("subagent_type") or ""
        return (f"Startet {wer} ({typ})" if typ else f"Startet {wer}"), _kurz(e.get("prompt", ""), MAX_DETAIL)
    if name in ("Grep", "Glob"):
        return f"Sucht in Dateien: {e.get('pattern', '')}", _kurz(e.get("path", ""), MAX_DETAIL)
    if name == "Skill":
        return f"Nutzt Skill /{e.get('skill', '')}", _kurz(str(e.get("args", "")), MAX_DETAIL)
    return name, _kurz(json.dumps(e, ensure_ascii=False), MAX_DETAIL)


def _nachricht(text: str, zeit: str, agent: str) -> dict | None:
    treffer = TEAMMATE_NACHRICHT.search(text)
    if not treffer:
        return None
    von, inhalt = treffer.group(1), treffer.group(2).strip()
    ev = {"zeit": zeit, "agent": agent, "art": "nachricht", "von": von, "text": _kurz(inhalt, MAX_NACHRICHT),
          "aufgabe": None, "beenden": False}
    if inhalt.startswith("{"):
        try:
            daten = json.loads(inhalt)
        except json.JSONDecodeError:
            daten = {}
        if isinstance(daten, dict) and daten.get("type") == "task_assignment":
            ev["aufgabe"] = daten.get("subject")
            ev["text"] = _kurz(f"Aufgabe #{daten.get('taskId', '?')}: {daten.get('subject', '')}", MAX_NACHRICHT)
            return ev
    m = AUFGABE_MUSTER.search(inhalt)
    if m:
        ev["aufgabe"] = m.group(1).strip()
    if von == "team-lead" and re.search(r"beende dich|bitte beenden|beende dich jetzt", inhalt, re.I):
        ev["beenden"] = True
    return ev


def _nutzer_text(text: str, zeit: str, agent: str) -> list[dict]:
    if text.lstrip().startswith("<teammate-message"):
        ev = _nachricht(text, zeit, agent)
        return [ev] if ev else []
    if text.startswith(RUECKMELDUNG_PRAEFIX):
        rest = text[len(RUECKMELDUNG_PRAEFIX):]
        kern = rest.split("]:", 1)[1] if "]:" in rest else rest
        return [{"zeit": zeit, "agent": agent, "art": "tuersteher_rueckmeldung", "text": _kurz(kern, MAX_NACHRICHT)}]
    return []


def ereignisse_aus_zeile(zeile: dict, agent: str, projekt: Path, preise: dict) -> list[dict]:
    typ = zeile.get("type")
    zeit = zeile.get("timestamp") or ""
    nachricht = zeile.get("message") or {}
    inhalt = nachricht.get("content")
    aus: list[dict] = []

    if typ == "assistant":
        modell = nachricht.get("model") or ""
        wire = zeile.get("wireToolInputs") or {}
        for block in inhalt if isinstance(inhalt, list) else []:
            if not isinstance(block, dict):
                continue
            b = block.get("type")
            if b == "text" and (block.get("text") or "").strip():
                aus.append({"zeit": zeit, "agent": agent, "art": "text", "text": _kurz(block["text"], MAX_TEXT)})
            elif b == "thinking":
                aus.append({"zeit": zeit, "agent": agent, "art": "denkt"})
            elif b == "tool_use":
                tid = block.get("id") or ""
                eingabe = wire.get(tid) if isinstance(wire.get(tid), dict) else (block.get("input") or {})
                if not isinstance(eingabe, dict):
                    eingabe = {}
                name = block.get("name") or "?"
                titel, detail = werkzeug_titel(name, eingabe, projekt)
                aus.append({"zeit": zeit, "agent": agent, "art": "werkzeug", "werkzeug": name, "titel": titel,
                            "detail": detail, "tool_use_id": tid,
                            "fertig_gemeldet": name == "TaskUpdate" and eingabe.get("status") == "completed"})
        usage = nachricht.get("usage")
        if isinstance(usage, dict):
            betrag, unbekannt = kosten_usd(usage, modell, preise)
            cc = usage.get("cache_creation") or {}
            gesamt = usage.get("cache_creation_input_tokens") or 0
            s1h, s5m = cc.get("ephemeral_1h_input_tokens"), cc.get("ephemeral_5m_input_tokens")
            if s1h is None and s5m is None:
                s5m, s1h = gesamt, 0
            aus.append({"zeit": zeit, "agent": agent, "art": "verbrauch", "modell": modell,
                        "input": usage.get("input_tokens") or 0, "output": usage.get("output_tokens") or 0,
                        "cache_lesen": usage.get("cache_read_input_tokens") or 0,
                        "cache_schreiben_5m": s5m or 0, "cache_schreiben_1h": s1h or 0,
                        "kosten_usd": betrag, "preis_unbekannt": unbekannt})
        return aus

    if typ == "user":
        if isinstance(inhalt, str):
            return _nutzer_text(inhalt, zeit, agent)
        for block in inhalt if isinstance(inhalt, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                aus.append({"zeit": zeit, "agent": agent, "art": "ergebnis", "tool_use_id": block.get("tool_use_id") or "",
                            "fehler": bool(block.get("is_error")),
                            "auszug": _kurz(_ergebnis_text(block.get("content")), MAX_DETAIL)})
            elif block.get("type") == "text":
                aus += _nutzer_text(block.get("text") or "", zeit, agent)
        return aus

    return []


def ereignis_aus_gate(zeile: dict) -> dict:
    return {"zeit": zeile.get("zeit") or "", "agent": zeile.get("teammate") or "lead", "art": "tuersteher",
            "entscheidung": zeile.get("entscheidung") or "?", "datei": zeile.get("datei") or "",
            "grund": zeile.get("grund") or "", "fehler": list(zeile.get("fehler") or [])[:MAX_FEHLER],
            "task_subject": zeile.get("task_subject") or ""}


# ---------------------------------------------------------------- Phase
def _relativ_zum_lauf(datei: str) -> str:
    teile = Path(datei).parts
    return "/".join(teile[2:]) if len(teile) > 2 and teile[0] == "runs" else datei


def phase_bestimmen(lauf_ordner: Path, gate_akzeptiert: set[str]) -> str:
    """Höchste zutreffende Phase aus akzeptierten Dateien (relativ zum Lauf) und vorhandenen Dateien."""
    lauf = Path(lauf_ordner)
    if (lauf / "report.html").is_file():
        return "Fertig"
    if "report.json" in gate_akzeptiert:
        return "Lektorat"
    if "redteam.json" in gate_akzeptiert:
        return "Report"
    shortlist = lauf / "shortlist.json"
    if (lauf / "redteam.json").is_file():
        return "Red Team"
    if shortlist.is_file():
        try:
            ticker = [a.get("ticker") for a in json.loads(shortlist.read_text(encoding="utf-8")).get("auswahl", [])]
        except (json.JSONDecodeError, AttributeError):
            ticker = []
        if ticker and all(f"firmen/{t}.json" in gate_akzeptiert for t in ticker):
            return "Red Team"
        return "Deep Dives"
    if PHASE_1_DATEIEN <= gate_akzeptiert:
        return "Screening"
    return "Phase 1"


# ---------------------------------------------------------------- Team und Karten
def _neue_karte(name: str, rolle: str, zeit: str) -> dict:
    return {"name": name, "rolle": rolle, "modell": "", "modell_kurz": "?", "zustand": "bereit", "zustand_seit": zeit,
            "aufgabe": "", "aktuell": "", "strom": [],
            "tokens": {"input": 0, "output": 0, "cache_lesen": 0, "cache_schreiben": 0},
            "kosten_usd": 0.0, "preis_unbekannt": False, "schritte": 0,
            "tuersteher": {"akzeptiert": 0, "abgelehnt": 0, "letzte": None},
            "gestartet": zeit, "zuletzt": zeit}


class Team:
    """Zustand aller Karten eines Laufs. verarbeite()/tick() liefern SSE-Paare (art, payload)."""

    def __init__(self, lauf_ordner: Path, projekt: Path, preise: dict, rollen: set[str],
                 uhr=time.time, modus: str = "live", replay_faktor: float = 1.0):
        self.lauf_ordner, self.projekt, self.preise, self.rollen = Path(lauf_ordner), Path(projekt), preise, set(rollen)
        self.uhr, self.modus, self.replay_faktor = uhr, modus, replay_faktor
        self.karten: dict[str, dict] = {}
        self._epoch: dict[str, float] = {}
        self._fertig_tool: dict[str, str] = {}
        self.gate_akzeptiert: set[str] = set()
        self.tuersteher = {"akzeptiert": 0, "abgelehnt": 0}
        self.lauf = self._lies_lauf()
        self.gestartet_epoch = zeit_epoch(self.lauf.get("gestartet") or "") or None
        self.phase = phase_bestimmen(self.lauf_ordner, self.gate_akzeptiert)

    # ---- Hilfen
    def _lies_lauf(self) -> dict:
        daten = {"ordner": str(self.lauf_ordner), "thema": self.lauf_ordner.name, "slug": "", "datum": "", "gestartet": ""}
        try:
            daten.update(json.loads((self.lauf_ordner / "lauf.json").read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
        return daten

    def karte(self, name: str) -> dict:
        return self.karten[name]

    def _kopf(self, k: dict) -> dict:
        return {key: val for key, val in k.items() if key != "strom"}

    def _lauf_kopf(self) -> dict:
        jetzt = self.uhr()
        start = self.gestartet_epoch or min(self._epoch.values(), default=jetzt)
        return {"lauf": self.lauf, "phase": self.phase, "phasen": PHASEN,
                "laufzeit_s": max(0.0, jetzt - start),
                "kosten_usd": sum(k["kosten_usd"] for k in self.karten.values()),
                "tokens": {f: sum(k["tokens"][f] for k in self.karten.values()) for f in ("input", "output", "cache_lesen", "cache_schreiben")},
                "tuersteher": dict(self.tuersteher), "agenten_anzahl": len(self.karten),
                "modus": self.modus, "replay_faktor": self.replay_faktor}

    def _reihenfolge(self) -> list[str]:
        def schluessel(name):
            k = self.karten[name]
            return (ROLLEN_REIHENFOLGE.index(k["rolle"]) if k["rolle"] in ROLLEN_REIHENFOLGE else 99,
                    zeit_epoch(k["gestartet"]), name)
        return sorted(self.karten, key=schluessel)

    def _karte_fuer(self, name: str, zeit: str) -> dict:
        if name not in self.karten:
            self.karten[name] = _neue_karte(name, rolle_aus_name(name, self.rollen), zeit)
        return self.karten[name]

    def _ziel_fuer_gate(self, ev: dict) -> str:
        """Gate-Zeilen ohne teammate_name stehen auf 'lead'; über die Aufgabe finden wir den echten Agenten."""
        name = ev["agent"]
        if name in self.karten and name != "lead":
            return name
        marke = f"[{ev.get('datei', '')}]"
        for k in self.karten.values():
            if ev.get("datei") and k["aufgabe"].startswith(marke):
                return k["name"]
        return name

    def _setze(self, k: dict, zustand: str, zeit: str) -> None:
        if k["zustand"] != zustand:
            k["zustand"], k["zustand_seit"] = zustand, zeit

    # ---- Ereignisse
    def verarbeite(self, ev: dict) -> list[tuple[str, dict]]:
        art, zeit = ev.get("art"), ev.get("zeit") or ""
        name = self._ziel_fuer_gate(ev) if art == "tuersteher" else ev.get("agent") or "lead"
        k = self._karte_fuer(name, zeit)
        k["zuletzt"] = zeit
        self._epoch[name] = zeit_epoch(zeit)
        aus: list[tuple[str, dict]] = []
        lauf_geaendert = False

        if art == "verbrauch":
            t = k["tokens"]
            t["input"] += ev.get("input", 0)
            t["output"] += ev.get("output", 0)
            t["cache_lesen"] += ev.get("cache_lesen", 0)
            t["cache_schreiben"] += ev.get("cache_schreiben_5m", 0) + ev.get("cache_schreiben_1h", 0)
            k["kosten_usd"] += ev.get("kosten_usd", 0.0)
            if ev.get("modell"):
                k["modell"], k["modell_kurz"] = ev["modell"], modell_kurz(ev["modell"])
            k["preis_unbekannt"] = k["preis_unbekannt"] or bool(ev.get("preis_unbekannt"))
            lauf_geaendert = True
        elif art == "text":
            if k["zustand"] != "wartet_tuersteher":
                self._setze(k, "schreibt", zeit)
        elif art == "denkt":
            if k["zustand"] != "wartet_tuersteher":
                self._setze(k, "denkt", zeit)
        elif art == "werkzeug":
            k["schritte"] += 1
            k["aktuell"] = ev.get("titel", "")
            if ev.get("fertig_gemeldet"):
                self._fertig_tool[name] = ev.get("tool_use_id", "")
                self._setze(k, "wartet_tuersteher", zeit)
            else:
                self._setze(k, "werkzeug", zeit)
        elif art == "ergebnis":
            if ev.get("tool_use_id") and ev.get("tool_use_id") == self._fertig_tool.get(name):
                self._setze(k, "korrigiert" if ev.get("fehler") else "bereit", zeit)
                self._fertig_tool.pop(name, None)
            elif k["zustand"] in ("untaetig", "fertig"):
                self._setze(k, "werkzeug", zeit)
        elif art == "nachricht":
            if ev.get("aufgabe"):
                k["aufgabe"] = ev["aufgabe"]
            if ev.get("beenden"):
                self._setze(k, "fertig", zeit)
            elif k["zustand"] in ("untaetig",):
                self._setze(k, "bereit", zeit)
        elif art == "tuersteher_rueckmeldung":
            self._setze(k, "korrigiert", zeit)
            self._fertig_tool.pop(name, None)
        elif art == "tuersteher":
            ok = ev.get("entscheidung") == "akzeptiert"
            k["tuersteher"]["akzeptiert" if ok else "abgelehnt"] += 1
            k["tuersteher"]["letzte"] = ev
            self.tuersteher["akzeptiert" if ok else "abgelehnt"] += 1
            self._setze(k, "bereit" if ok else "korrigiert", zeit)
            self._fertig_tool.pop(name, None)
            if ok and ev.get("datei"):
                self.gate_akzeptiert.add(_relativ_zum_lauf(ev["datei"]))
            self.phase = phase_bestimmen(self.lauf_ordner, self.gate_akzeptiert)
            lauf_geaendert = True
            ev = dict(ev, agent=name)
        else:
            return aus

        if art in STROM_ARTEN:
            k["strom"].append(ev)
            del k["strom"][:-MAX_STROM]
            aus.append(("ereignis", ev))
        aus.append(("karte", self._kopf(k)))
        if lauf_geaendert:
            aus.append(("lauf", self._lauf_kopf()))
        return aus

    def tick(self) -> list[tuple[str, dict]]:
        jetzt = self.uhr()
        aus: list[tuple[str, dict]] = []
        for name, k in self.karten.items():
            still = jetzt - self._epoch.get(name, jetzt)
            zeit = datetime.fromtimestamp(jetzt, tz=timezone.utc).isoformat(timespec="seconds")
            if k["zustand"] == "fertig":
                continue
            if still > FERTIG_S:
                self._setze(k, "fertig", zeit)
                aus.append(("karte", self._kopf(k)))
            elif still > UNTAETIG_S and k["zustand"] != "untaetig":
                self._setze(k, "untaetig", zeit)
                aus.append(("karte", self._kopf(k)))
        neue_phase = phase_bestimmen(self.lauf_ordner, self.gate_akzeptiert)
        if neue_phase != self.phase:
            self.phase = neue_phase
        if not self.lauf.get("gestartet"):
            self.lauf = self._lies_lauf()
            self.gestartet_epoch = zeit_epoch(self.lauf.get("gestartet") or "") or None
        aus.append(("lauf", self._lauf_kopf()))
        return aus

    def snapshot(self) -> dict:
        snap = self._lauf_kopf()
        snap["agenten"] = {name: k for name, k in self.karten.items()}
        snap["reihenfolge"] = self._reihenfolge()
        snap["erwartet"] = list(ERWARTET)
        return snap
