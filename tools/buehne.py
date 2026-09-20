#!/usr/bin/env python3
"""Bühne – Live-Fenster für einen /thema-Lauf: ein Raster von Agenten-Karten im Browser.

Liest (und schreibt nichts):
  • die Transkripte des Leads und seiner Teammates unter ~/.claude/projects/<projekt>/*.jsonl
  • runs/<lauf>/gate-log.jsonl (Türsteher) und den Lauf-Ordner (Phase)
und pusht Ereignisse per Server-Sent Events an templates/buehne.html.

    python3 tools/buehne.py runs/<lauf> --open              # live, http://127.0.0.1:8767
    python3 tools/buehne.py runs/<lauf> --replay --speed 10 # Lauf aus den Transkripten abspielen
    python3 tools/buehne.py runs/<lauf> --lead <session-id> # Lead-Transkript fest vorgeben

Exit-Codes: 0 ok · 1 Bedienfehler (Lauf fehlt, kein Lead gefunden) · 2 Port belegt.
Nur Standardbibliothek; lauscht ausschließlich auf 127.0.0.1.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import queue
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buehne_modell as bm  # noqa: E402
from gemeinsam import PROJEKT, ToolFehler, ausfuehren  # noqa: E402

SEITE = PROJEKT / "templates" / "buehne.html"
LESE_TAKT_S = 0.15       # Transkripte fortlesen
SUCH_TAKT_S = 2.0        # nach neuen Teammates suchen
TICK_TAKT_S = 1.0        # Laufzeit, Untätig-Schwellen
REPLAY_MAX_PAUSE_S = 3.0
REPLAY_NACHLAUF_S = 600.0   # nach der letzten Türsteher-Entscheidung: Render, Abschied der Teammates
KOPFZEILEN = 40          # so viele Zeilen eines Transkripts reichen für cwd/agentName/teamName


# ---------------------------------------------------------------- Transkripte finden
def projekt_slug(projekt: Path) -> str:
    """Claude Code bildet den Ordnernamen aus dem absoluten Pfad: jedes Zeichen außer [A-Za-z0-9] wird '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(projekt))


def transkript_ordner(projekt: Path) -> Path:
    basis = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    return basis / "projects" / projekt_slug(projekt)


def session_id(pfad: Path) -> str:
    return pfad.stem


def _kopf_infos(pfad: Path) -> dict:
    """cwd, agentName, teamName und erster Zeitstempel aus den ersten Zeilen eines Transkripts."""
    info = {"cwd": "", "agentName": "", "teamName": "", "zeit": ""}
    try:
        with pfad.open("r", encoding="utf-8", errors="replace") as f:
            for i, zeile in enumerate(f):
                if i >= KOPFZEILEN:
                    break
                try:
                    d = json.loads(zeile)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                for feld in ("cwd", "agentName", "teamName"):
                    if d.get(feld) and not info[feld]:
                        info[feld] = d[feld]
                if d.get("timestamp") and not info["zeit"]:
                    info["zeit"] = d["timestamp"]
    except OSError:
        pass
    return info


def rollen_aus_projekt(projekt: Path) -> set[str]:
    ordner = projekt / ".claude" / "agents"
    rollen = {p.stem for p in ordner.glob("*.md")} if ordner.is_dir() else set()
    return rollen or {"markt", "treiber", "kette", "firma", "red-team", "lektor"}


LEAD_SPIELRAUM_S = 60    # der Lead startet kurz vor lauf.json.gestartet


def finde_lead(ordner: Path, projekt: Path, lead_id: str | None, nach: str | None) -> Path | None:
    """Das Lead-Transkript: ohne agentName, cwd im Projekt.

    Ohne `nach`: das zuletzt geänderte. Mit `nach` (Zeitpunkt, z. B. lauf.json.gestartet): die Session, die
    zu diesem Zeitpunkt lief – die zuletzt gestartete mit Beginn vor `nach` (+ Spielraum); gibt es keine,
    die erste danach. Eine Lead-Session kann mehrere Läufe enthalten, deshalb zählt der Beginn, nicht das Ende.
    """
    if lead_id:
        pfad = ordner / f"{lead_id}.jsonl"
        return pfad if pfad.is_file() and not _kopf_infos(pfad)["agentName"] else None
    projekt_str = str(projekt)
    kandidaten = []
    for pfad in ordner.glob("*.jsonl"):
        info = _kopf_infos(pfad)
        if info["agentName"] or not info["cwd"].startswith(projekt_str):
            continue
        try:
            kandidaten.append((bm.zeit_epoch(info["zeit"]), pfad.stat().st_mtime, pfad))
        except OSError:
            continue
    if not kandidaten:
        return None
    if not nach:
        return max(kandidaten, key=lambda k: k[1])[2]
    grenze = bm.zeit_epoch(nach) + LEAD_SPIELRAUM_S
    davor = [k for k in kandidaten if k[0] <= grenze]
    if davor:
        return max(davor, key=lambda k: k[0])[2]
    return min(kandidaten, key=lambda k: k[0])[2]


def team_name(lead_id: str) -> set[str]:
    """Claude Code nennt das Team nach den ersten 8 Zeichen der Lead-Session-ID (session-9b756dd5)."""
    return {f"session-{lead_id}", f"session-{lead_id[:8]}"}


def finde_teammates(ordner: Path, lead_id: str, von: float = 0.0, bis: float = 0.0) -> list[Path]:
    """Transkripte mit passendem teamName; optional nur solche, die im Zeitfenster [von, bis] begonnen haben."""
    namen = team_name(lead_id)
    aus = []
    for p in ordner.glob("*.jsonl"):
        info = _kopf_infos(p)
        if info["teamName"] not in namen:
            continue
        start = bm.zeit_epoch(info["zeit"])
        if (von and start < von) or (bis and start > bis):
            continue
        aus.append(p)
    return sorted(aus)


# ---------------------------------------------------------------- Dateien fortlesen
class Tailer:
    """Liest eine JSONL-Datei ab der gemerkten Position weiter – nur vollständige Zeilen."""

    def __init__(self, pfad: Path):
        self.pfad, self.pos = pfad, 0

    def lies(self) -> list[dict]:
        try:
            groesse = self.pfad.stat().st_size
        except OSError:
            return []
        if groesse < self.pos:
            self.pos = 0
        if groesse == self.pos:
            return []
        with self.pfad.open("rb") as f:
            f.seek(self.pos)
            rest = f.read()
        schnitt = rest.rfind(b"\n")
        if schnitt < 0:
            return []
        self.pos += schnitt + 1
        aus = []
        for zeile in rest[:schnitt].decode("utf-8", "replace").splitlines():
            try:
                d = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict):
                aus.append(d)
        return aus


def replay_ereignisse(pfade: list[Path], gate_log: Path | None, projekt: Path, preise: dict,
                      von: float = 0.0, bis: float = 0.0) -> list[dict]:
    """Alle Ereignisse eines Teams plus Türsteher, nach Zeit sortiert (stabil); optional auf [von, bis] begrenzt."""
    evs: list[dict] = []
    for pfad in pfade:
        for z in Tailer(pfad).lies():
            evs += bm.ereignisse_aus_zeile(z, bm.agent_aus_zeile(z), projekt, preise)
    if gate_log and gate_log.is_file():
        evs += [bm.ereignis_aus_gate(z) for z in Tailer(gate_log).lies()]
    if von or bis:
        evs = [e for e in evs if (not von or bm.zeit_epoch(e.get("zeit") or "") >= von)
               and (not bis or bm.zeit_epoch(e.get("zeit") or "") <= bis)]
    return sorted(evs, key=lambda e: bm.zeit_epoch(e.get("zeit") or ""))


def replay_fenster(lauf: Path, gestartet: str | None) -> tuple[float, float]:
    """Zeitfenster eines Laufs: ab kurz vor lauf.json.gestartet bis zur letzten Türsteher-Entscheidung + Nachlauf."""
    von = bm.zeit_epoch(gestartet) - LEAD_SPIELRAUM_S if gestartet else 0.0
    bis = 0.0
    gate = lauf / "gate-log.jsonl"
    if gate.is_file():
        zeiten = [bm.zeit_epoch(z.get("zeit") or "") for z in Tailer(gate).lies()]
        if zeiten:
            bis = max(zeiten) + REPLAY_NACHLAUF_S
    return max(von, 0.0), bis


# ---------------------------------------------------------------- Zustand + Verteilung
class Zustand:
    def __init__(self, team: bm.Team):
        self.team = team
        self.lock = threading.Lock()
        self.abonnenten: list[queue.Queue] = []

    def abonnieren(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self.lock:
            self.abonnenten.append(q)
            q.put(("init", self.team.snapshot()))
        return q

    def abbestellen(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.abonnenten:
                self.abonnenten.remove(q)

    def _verteile(self, paare) -> None:
        for paar in paare:
            for q in self.abonnenten:
                try:
                    q.put_nowait(paar)
                except queue.Full:
                    pass

    def verarbeite(self, ereignisse: list[dict]) -> None:
        with self.lock:
            for ev in ereignisse:
                self._verteile(self.team.verarbeite(ev))

    def tick(self) -> None:
        with self.lock:
            self._verteile(self.team.tick())

    def setze_modus(self, modus: str) -> None:
        with self.lock:
            self.team.modus = modus
            if modus == "replay-ende":
                self._verteile(self.team.alle_fertig())
            self._verteile([("lauf", self.team._lauf_kopf())])

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.team.snapshot(), ensure_ascii=False))


class LiveLeser(threading.Thread):
    """Folgt Lead, Teammates und Gate-Log; sucht regelmäßig nach neuen Teammates."""

    def __init__(self, zustand: Zustand, ordner: Path, projekt: Path, lead: Path, gate_log: Path, preise: dict):
        super().__init__(daemon=True)
        self.zustand, self.ordner, self.projekt, self.preise = zustand, ordner, projekt, preise
        self.lead_id = session_id(lead)
        self.tailer: dict[Path, Tailer] = {lead: Tailer(lead)}
        self.gate = Tailer(gate_log)
        self.stop = threading.Event()

    def _suche(self) -> None:
        for pfad in finde_teammates(self.ordner, self.lead_id):
            if pfad not in self.tailer:
                self.tailer[pfad] = Tailer(pfad)
                print(f"  + Teammate: {pfad.name}", flush=True)

    def _lies_alles(self) -> None:
        evs: list[dict] = []
        for t in list(self.tailer.values()):
            for z in t.lies():
                evs += bm.ereignisse_aus_zeile(z, bm.agent_aus_zeile(z), self.projekt, self.preise)
        evs += [bm.ereignis_aus_gate(z) for z in self.gate.lies()]
        if evs:
            evs.sort(key=lambda e: bm.zeit_epoch(e.get("zeit") or ""))
            self.zustand.verarbeite(evs)

    def run(self) -> None:
        self._suche()
        letzte_suche = letzter_tick = time.time()
        while not self.stop.is_set():
            self._lies_alles()
            jetzt = time.time()
            if jetzt - letzte_suche > SUCH_TAKT_S:
                self._suche()
                letzte_suche = jetzt
            if jetzt - letzter_tick > TICK_TAKT_S:
                self.zustand.tick()
                letzter_tick = jetzt
            self.stop.wait(LESE_TAKT_S)


class Replayer(threading.Thread):
    """Spielt die Ereignisse eines Teams im Zeitraffer ab; die Uhr des Teams folgt der Aufzeichnung."""

    def __init__(self, zustand: Zustand, ereignisse: list[dict], speed: float):
        super().__init__(daemon=True)
        self.zustand, self.ereignisse, self.speed = zustand, ereignisse, max(speed, 0.01)
        self.stop = threading.Event()
        self.jetzt = bm.zeit_epoch(ereignisse[0]["zeit"]) if ereignisse else time.time()
        zustand.team.uhr = lambda: self.jetzt

    def run(self) -> None:
        vorher = None
        letzter_tick = 0.0
        for ev in self.ereignisse:
            if self.stop.is_set():
                return
            t = bm.zeit_epoch(ev.get("zeit") or "")
            if vorher is not None and t > vorher:
                pause = min((t - vorher) / self.speed, REPLAY_MAX_PAUSE_S)
                self.stop.wait(pause)
            if t:
                vorher = t
                self.jetzt = max(self.jetzt, t)
            self.zustand.verarbeite([ev])
            if self.jetzt - letzter_tick > 5:
                self.zustand.tick()
                letzter_tick = self.jetzt
        self.zustand.tick()
        self.zustand.setze_modus("replay-ende")
        print("  ▶ Replay beendet", flush=True)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    zustand: Zustand = None  # wird von starte_server gesetzt

    def log_message(self, *a):  # still
        pass

    def _antwort(self, body: bytes, typ: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        pfad = urlparse(self.path).path
        if pfad in ("/", "/index.html"):
            if not SEITE.is_file():
                return self._antwort("templates/buehne.html fehlt.".encode(), "text/plain; charset=utf-8", 500)
            return self._antwort(SEITE.read_bytes(), "text/html; charset=utf-8")
        if pfad == "/api/state":
            return self._antwort(json.dumps(self.zustand.snapshot(), ensure_ascii=False).encode(), "application/json; charset=utf-8")
        if pfad == "/api/events":
            return self._sse()
        self._antwort(b"nicht gefunden", "text/plain; charset=utf-8", 404)

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.zustand.abonnieren()
        try:
            while True:
                try:
                    art, payload = q.get(timeout=15)
                    self.wfile.write(f"event: {art}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.zustand.abbestellen(q)


def starte_server(lauf: Path, projekt: Path, port: int, replay: bool, speed: float,
                  lead_id: str | None) -> ThreadingHTTPServer:
    """Baut Team, Leser bzw. Replayer und HTTP-Server; der Server läuft in einem Daemon-Thread."""
    lauf = Path(lauf)
    if not lauf.is_dir():
        raise ToolFehler(f"Lauf-Ordner {lauf} existiert nicht. Erst /thema starten (oder einen Ordner unter runs/ angeben).")
    preise = bm.lade_preise()
    ordner = transkript_ordner(projekt)
    gate_log = lauf / "gate-log.jsonl"
    gestartet = None
    try:
        gestartet = json.loads((lauf / "lauf.json").read_text(encoding="utf-8")).get("gestartet")
    except (OSError, json.JSONDecodeError):
        pass
    lead = finde_lead(ordner, projekt, lead_id, nach=gestartet if replay else None) if ordner.is_dir() else None
    if lead is None:
        raise ToolFehler("Kein Lead-Transkript gefunden. Starte im Projektordner `claude --teammate-mode tmux` und "
                         f"dann /thema – oder gib das Transkript mit --lead <session-id> an (gesucht in {ordner}).")

    team = bm.Team(lauf, projekt, preise, rollen_aus_projekt(projekt),
                   modus="replay" if replay else "live", replay_faktor=speed if replay else 1.0)
    zustand = Zustand(team)
    if replay:
        von, bis = replay_fenster(lauf, gestartet)
        pfade = [lead] + finde_teammates(ordner, session_id(lead), von, bis)
        evs = replay_ereignisse(pfade, gate_log, projekt, preise, von, bis)
        print(f"  ▶ Replay: {len(pfade)} Transkripte, {len(evs)} Ereignisse, Faktor {speed}", flush=True)
        arbeiter: threading.Thread = Replayer(zustand, evs, speed)
    else:
        print(f"  ▶ Lead: {lead.name}", flush=True)
        arbeiter = LiveLeser(zustand, ordner, projekt, lead, gate_log, preise)

    Handler.zustand = zustand
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, 48, 98):
            raise PortBelegt(port)
        raise
    server.daemon_threads = True
    arbeiter.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class PortBelegt(Exception):
    def __init__(self, port: int):
        super().__init__(f"Port {port} ist belegt. Anderen Port wählen: --port {port + 1}")


# ---------------------------------------------------------------- CLI
def main() -> int:
    ap = argparse.ArgumentParser(description="Bühne – Live-Fenster für einen /thema-Lauf (nur lesen, nur 127.0.0.1)")
    ap.add_argument("lauf", help="Lauf-Ordner, z. B. runs/robotik-2026-09-18")
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--open", action="store_true", help="Browser öffnen")
    ap.add_argument("--lead", help="Session-ID des Lead-Transkripts statt Auto-Erkennung")
    ap.add_argument("--replay", action="store_true", help="Lauf aus den Transkripten abspielen statt live")
    ap.add_argument("--speed", type=float, default=10.0, help="Replay-Faktor (Standard 10)")
    a = ap.parse_args()

    try:
        server = starte_server(Path(a.lauf), PROJEKT, a.port, a.replay, a.speed, a.lead)
    except PortBelegt as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"  ▶ Bühne: {url}   (Strg+C beendet)", flush=True)
    if a.open:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        print("\n  ■ Bühne beendet", flush=True)
    return 0


if __name__ == "__main__":
    ausfuehren(main)
