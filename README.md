# thema-research

Ein Team aus Claude-Code-Agenten recherchiert einen Investment-Trend (z. B. „Robotik“) und erzeugt daraus einen Thematic-Research-Report im Stil eines institutionellen Asset Managers – als einzelne, offline lesbare HTML-Datei.

**Die KI urteilt, der Code kontrolliert.** Agenten recherchieren, bewerten und schreiben JSON nach Schema. Datenabruf, Screening, Zusammenführen, Validierung und Rendering sind deterministischer Python-Code. Ein Türsteher-Hook weist jede Aufgabe zurück, deren Datei nicht gültig ist.

> **Keine Anlageberatung.** Das Projekt dient Lern- und Demonstrationszwecken. Es gibt keine Kauf- oder Verkaufsempfehlungen und keine Kursziele.

## Ablauf eines Laufs

```
/thema robotik
  │
  ├─ Phase 1 (parallel)   markt ─ treiber ─ kette              → markt-groesse.json, treiber.json, kette.json
  ├─ Code                 merge_markt.py → screen.py          → markt.json, universum.json
  ├─ Lead                 wählt 6–8 Firmen                    → shortlist.json
  ├─ Phase 2 (parallel)   firma-1 … firma-4, eine Firma je Aufgabe → firmen/<TICKER>.json
  ├─ Red Team             bottom_up.py + Bear Case zu allem   → bottom_up.json, redteam.json
  └─ Lead                 Report nach Skill report-stil       → report.json → render.py → report.html
```

Jede Aufgabe trägt ihre Ergebnisdatei im Titel (`[runs/<lauf>/kette.json] Wertschöpfungskette`). Beim Abschließen prüft `tools/gate.py` die Datei gegen ihr Schema; bei Fehlern bleibt die Aufgabe offen und der Agent bekommt die Fehlerliste zurück. Jede Entscheidung landet in `runs/<lauf>/gate-log.jsonl` und erscheint im Report als Türsteher-Statistik.

## Setup

Voraussetzungen: Python 3.11+, [Claude Code](https://code.claude.com), für die Split-Pane-Ansicht tmux oder iTerm2.

```bash
python3 -m venv .venv            # oder: uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Die Hooks rufen `.venv/bin/python3` direkt auf – das venv muss also unter diesem Namen im Projektordner liegen.

## Einen Lauf starten

Im **aktivierten venv** (die Agenten rufen die Tools als `python3 tools/…` auf) in iTerm2 oder tmux:

```bash
source .venv/bin/activate
claude --teammate-mode tmux
```

Dann in Claude Code:

```
/thema robotik
```

Ohne tmux/iTerm2 funktioniert auch `claude` allein; die Teammates erscheinen dann im Agenten-Panel unter der Eingabezeile (Pfeiltasten + Enter).

> **Hinweise:** Agent Teams sind eine **experimentelle** Funktion von Claude Code (aktiviert über `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `.claude/settings.json`). Ein Lauf startet bis zu neun Agenten mit je eigenem Kontext und verbraucht **deutlich mehr Tokens** als eine einzelne Session. Das Red Team läuft auf Opus.

Das Ergebnis liegt in `runs/<thema>-<datum>/report.html`.

## Tools einzeln

Jedes Tool hat `--help`, deutsche Fehlermeldungen und sinnvolle Exit-Codes.

| Tool | Zweck |
|---|---|
| `tools/validate.py <datei…>` | Prüft Dateien gegen ihr Schema (Schema aus dem Dateinamen), löst `{ref:…}`-Verweise im Report auf |
| `tools/kennzahlen.py TICKER… [--offline] [--neu]` | Holt Kennzahlen per yfinance als Zahl-Objekte nach `data/kennzahlen/` |
| `tools/merge_markt.py <lauf>` | Führt die Phase-1-Ergebnisse zu `markt.json` zusammen |
| `tools/screen.py <lauf> [--offline]` | Screening nach `tools/screen_regeln.json`, schreibt `universum.json` |
| `tools/bottom_up.py <lauf>` | Summe der Themen-Umsätze gegen die Top-down-Spanne |
| `tools/render.py <lauf> [--open]` | Rendert den Report als eigenständige HTML-Datei |
| `tools/gate.py`, `tools/gate_create.py` | Türsteher-Hooks (lesen Hook-JSON von stdin) |

## Ohne Agenten ausprobieren

```bash
# Schemas und Validator
python3 tools/validate.py tests/fixtures/gut/*.json       # alles ✓
python3 tools/validate.py tests/fixtures/kaputt/*.json    # verständliche Fehlerliste

# Türsteher-Hooks
bash tests/test_gate.sh

# Renderer mit einem vollständig fiktiven Beispiel-Lauf
python3 tools/render.py tests/fixtures/beispiel-lauf --open

# Werkzeugkette mit echten Tickern (Testdaten, braucht Internet)
cp -r tests/fixtures/test-lauf runs/test-lauf
python3 tools/merge_markt.py runs/test-lauf
python3 tools/screen.py runs/test-lauf
python3 tools/bottom_up.py runs/test-lauf
```

## Aufbau

```
.claude/
  settings.json            Agent Teams, Hooks, vorab erlaubte Berechtigungen
  agents/                  Rollen: markt, treiber, kette, firma, red-team
  skills/thema/            Drehbuch für den Lead (/thema)
  skills/report-stil/      Ton, Aufbau und Zahlen-Schreibweise des Reports
schemas/                   JSON-Schemas; zahl.schema.json ist das Herzstück
tools/                     deterministischer Code (siehe oben)
templates/report.html.j2   Report-Layout
data/                      Kennzahlen und Cache (nicht versioniert)
runs/                      ein Ordner pro Lauf (nicht versioniert)
tests/                     Fixtures, fiktiver Beispiel-Lauf, Hook-Test
docs/bauauftrag.md         Der ursprüngliche Bauauftrag inkl. Nachträgen
```

## Grundregeln

- **Keine Zahl ohne Herkunft:** Jede Zahl ist ein Zahl-Objekt – `berichtet` mit Quelle oder `schaetzung` mit Begründung. Im Report stehen Zahlen nur als Verweis `{ref:<datei>#<json-pointer>}`; der Renderer setzt Wert und Fußnote ein.
- **Datei-Eigentum:** Jeder Agent schreibt nur seine eigene Datei.
- **Keine Anlageberatung** und keine Namen, Logos oder Markenelemente realer Asset Manager.
