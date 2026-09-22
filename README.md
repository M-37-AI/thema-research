# thema-research

> **English summary:** A team of Claude Code agents researches an investment theme (e.g. "robotics") and produces a thematic research report in the style of an institutional asset manager, as a single offline HTML file. Agents research, judge and write JSON; deterministic Python code fetches data, screens companies, validates every file and renders the report. A hook ("gatekeeper") rejects any task whose output file fails its schema. Everything else in this repository is in German. Not investment advice.

Ein Team aus Claude-Code-Agenten recherchiert einen Investment-Trend (z. B. „Robotik“) und erzeugt daraus einen Thematic-Research-Report im Stil eines institutionellen Asset Managers – als einzelne, offline lesbare HTML-Datei.

**Die KI urteilt, der Code kontrolliert.** Agenten recherchieren, bewerten und schreiben JSON nach Schema. Datenabruf, Screening, Zusammenführen, Validierung und Rendering sind deterministischer Python-Code. Ein Türsteher-Hook weist jede Aufgabe zurück, deren Datei nicht gültig ist. **Keine Zahl ohne Herkunft:** Jede Zahl im Report trägt eine Quelle oder ist als Schätzung mit Begründung markiert.

> **Keine Anlageberatung.** Das Projekt dient Lern- und Demonstrationszwecken. Es gibt keine Kauf- oder Verkaufsempfehlungen und keine Kursziele.

**Beispiele** (echte, unveränderte Läufe – einfach `report.html` im Browser öffnen):
- `examples/robotik-2026-09-18/` – Robotik: 8 Firmen, 14 Einwände des Red Teams, 36 belegte Zahlen. Ergebnis: „einstelliges Volumenwachstum, zweistellige Prognosen hängen an den Humanoiden“.
- `examples/batterierecycling-2026-09-19/` – Batterierecycling: 8 Firmen, 19 Einwände. Ergebnis: „politisch gewolltes Thema ohne investierbare Aktie“ – kein Kernprofiteur über 1 Mrd USD. Lief ohne einen manuellen Eingriff in 23 Minuten für ≈ 15 $ (API-Listenpreise; Details in `docs/testlauf-2-2026-09-19.md`).

## Ablauf eines Laufs

```
/thema robotik
  │
  ├─ Phase 1 (parallel)   markt · treiber · kette                → markt-groesse.json, treiber.json, kette.json
  ├─ Code                 merge_markt.py → screen.py            → markt.json, universum.json
  ├─ Lead                 wählt 6–8 Firmen über alle Segmente   → shortlist.json
  ├─ Phase 2 (parallel)   firma-1 … firma-4, je eine Firma pro Aufgabe → firmen/<TICKER>.json
  ├─ Red Team (Opus)      bottom_up.py + Bear Case zu allem      → bottom_up.json, redteam.json
  ├─ Lead                 Report nach Skill report-stil          → report.json
  ├─ Lektor (Opus)        Sprache für Laien, Zahlen unverändert  → lektorat.json
  └─ Code                 render.py                              → report.html
```

Jede Aufgabe trägt ihre Ergebnisdatei im Titel (`[runs/<lauf>/kette.json] Wertschöpfungskette`). Beim Abschließen prüft `tools/gate.py` die Datei gegen ihr Schema; bei Fehlern bleibt die Aufgabe offen, und der Agent bekommt die Fehlerliste zurück. Jede Entscheidung landet in `runs/<lauf>/gate-log.jsonl` und erscheint im Report als Türsteher-Statistik.

| Teammate | Modell | Aufgabe |
|---|---|---|
| `markt` | Sonnet | ≥ 3 unabhängige Marktschätzungen mit expliziter Abgrenzung, nicht gemittelt |
| `treiber` | Sonnet | Treiber und Hürden, jeweils belegt |
| `kette` | Sonnet | 5–8 Segmente der Wertschöpfungskette mit börsennotierten Kandidaten (yfinance-Ticker) |
| `firma-1` … `firma-4` | Sonnet | Deep Dive je Firma: Kennzahlen per Tool, Themen-Exposure, Rolle, Bull/Bear Case |
| `red-team` | Opus | greift Prognosen, Exposures und Etikettenschwindel an; rechnet den Bottom-up-Check |
| `lektor` | Opus | überarbeitet alle Texte für interessierte Laien; Code prüft, dass keine Zahl sich ändert |
| Lead (deine Session) | dein Modell | koordiniert, wählt die Shortlist, schreibt den Report, beantwortet schwere Einwände |

## Voraussetzungen

- **macOS 13+ oder Linux.** (Windows ungetestet: Die Hook-Pfade in `.claude/settings.json` müssten auf `.venv\Scripts\python.exe` geändert werden.)
- **Python 3.11 oder neuer.** Das macOS-eigene `python3` ist 3.9 und reicht **nicht**. Am einfachsten über [uv](https://docs.astral.sh/uv/), das Python 3.12 bei Bedarf selbst lädt.
- **tmux** für die Split-Pane-Ansicht (empfohlen; ohne tmux erscheinen die Teammates im Agenten-Panel unter der Eingabezeile).
- **[Claude Code](https://code.claude.com/docs/en/setup) ≥ 2.1.178** mit einem Pro-, Max- oder Team-Abo oder API-Zugang; das Projekt nutzt Opus und Sonnet.
- Internet für Websuche und Yahoo Finance. Keine API-Keys nötig.

**Kosten und Dauer:** Ein Lauf startet bis zu **neun Agenten** mit je eigenem Kontext (7 × Sonnet, 2 × Opus plus Lead) und dauert etwa 20–40 Minuten. Das verbraucht deutlich mehr Tokens als eine normale Session. Referenz: Der Batterierecycling-Lauf kostete **≈ 15 $ zu API-Listenpreisen** (Lead auf Fable 5.1 5,83 $, Red Team und Lektor auf Opus je ~3,40 $, alle sieben Sonnet-Agenten zusammen 2,50 $), der Quantencomputing-Lauf ≈ 19 $. Auf einem Max-Abo zählt stattdessen Kontingent. **`/cost` im Lead zeigt nur den Lead** – Teammates in tmux-Panes sind eigene Prozesse; ihre Kosten stehen in den Transkripten unter `~/.claude/projects/`.

## Installation

macOS mit [Homebrew](https://brew.sh):

```bash
# 1. Werkzeuge (einmalig)
brew install uv tmux
curl -fsSL https://claude.ai/install.sh | bash     # Claude Code; danach einmal `claude` starten und anmelden
claude --version                                    # ≥ 2.1.178

# 2. Projekt
git clone https://github.com/M-37-AI/thema-research.git && cd thema-research
uv venv --python 3.12 .venv                         # lädt Python 3.12, falls nicht vorhanden
source .venv/bin/activate
uv pip install -r requirements.txt                  # für Tests: requirements-dev.txt

# 3. Prüfen
python3 tools/check_setup.py --online               # Python, Pakete, Claude Code, Hooks, tmux, Yahoo
```

Linux: uv per `curl -LsSf https://astral.sh/uv/install.sh | sh`, tmux über den Paketmanager (`sudo apt install tmux`), Rest wie oben.

Ohne uv geht es mit einem eigenen Python ≥ 3.11 (z. B. `brew install python@3.12`): `python3.12 -m venv .venv`, `source .venv/bin/activate`, `pip install -r requirements.txt`. In einem mit uv angelegten venv gibt es kein `pip`; dort immer `uv pip install` verwenden.

Das venv **muss** `.venv` heißen und im Projektordner liegen: Die Hooks rufen `.venv/bin/python3` direkt auf.

## Einen Lauf starten

```bash
source .venv/bin/activate             # die Agenten rufen die Tools als python3 tools/… auf
claude --teammate-mode tmux           # in iTerm2 oder in einer tmux-Session
```

Beim **ersten Start** fragt Claude Code, ob du dem Ordner vertraust, und listet die vorab erlaubten Rechte aus `.claude/settings.json` auf (WebSearch, WebFetch, `python3 tools/*`, Schreiben in `runs/` und `data/`). Bestätigen, sonst landet jede Rückfrage der Teammates beim Lead.

Dann in Claude Code:

```
/thema robotik
```

Der Lead legt den Lauf-Ordner an, startet die Teammates und meldet sich mit der Universum-Tabelle, wenn Phase 1 fertig ist. Danach läuft alles ohne Eingriff bis zum fertigen Report; am Ende bittet der Lead dich um `/cost`. Das Ergebnis liegt in `runs/<thema>-<datum>/report.html` (und zum Vergleich `report-ohne-lektorat.html`).

**Permission-Modus:** Am reibungslosesten läuft es im Auto-Modus (`shift+tab`) oder mit `--permission-mode acceptEdits`. Im Standardmodus fragen Teammates für Befehle außerhalb der Freigaben beim Lead nach.

**Zuschauen:** In tmux bekommt jeder Teammate ein eigenes Pane. Ohne tmux: Pfeiltasten im Agenten-Panel, Enter öffnet das Transkript eines Teammates.

## Ohne Agenten ausprobieren

```bash
bash tests/run_all.sh                                   # pytest + Hook-Tests + Fixtures, offline
python3 tools/render.py tests/fixtures/beispiel-lauf --open   # fiktiver Beispiel-Lauf rendern
python3 tools/render.py examples/robotik-2026-09-18 --open    # echter Lauf neu rendern

# Werkzeugkette mit echten Tickern (braucht Internet)
cp -r tests/fixtures/test-lauf runs/test-lauf
python3 tools/merge_markt.py runs/test-lauf && python3 tools/screen.py runs/test-lauf && python3 tools/bottom_up.py runs/test-lauf
```

## Tools

Jedes Tool hat `--help`, deutsche Fehlermeldungen und sinnvolle Exit-Codes.

| Tool | Zweck |
|---|---|
| `tools/check_setup.py [--online]` | Voraussetzungen prüfen |
| `tools/validate.py <datei…>` | Dateien gegen ihr Schema prüfen (Schema aus dem Dateinamen); löst `{ref:…}`-Verweise auf; prüft Lektorate |
| `tools/kennzahlen.py TICKER… [--offline] [--neu]` | Kennzahlen per yfinance als Zahl-Objekte nach `data/kennzahlen/`, mit Plausibilitätsprüfung |
| `tools/merge_markt.py <lauf>` | Phase-1-Ergebnisse zu `markt.json` zusammenführen |
| `tools/screen.py <lauf> [--offline]` | Screening nach `tools/screen_regeln.json`, Shortlist-Vorschlag im Segment-Rundlauf |
| `tools/bottom_up.py <lauf>` | Summe der Themen-Umsätze gegen die Top-down-Spanne |
| `tools/lektorat_vorlage.py <lauf>` | alle im Report sichtbaren Texte als Vorlage für den Lektor |
| `tools/render.py <lauf> [--open] [--ohne-lektorat]` | validiert alle Dateien des Laufs und rendert den Report (reines SVG/HTML, ~0,1 MB) |
| `tools/gate.py`, `tools/gate_create.py` | Türsteher-Hooks (lesen Hook-JSON von stdin) |

## Aufbau

```
.claude/
  settings.json            Agent Teams, Task-Tools, Hooks, vorab erlaubte Berechtigungen
  agents/                  Rollen: markt, treiber, kette, firma, red-team, lektor
  skills/thema/            Drehbuch für den Lead (/thema)
  skills/report-stil/      Ton, Aufbau und Zahlen-Schreibweise des Reports
schemas/                   JSON-Schemas; zahl.schema.json ist das Herzstück
tools/                     deterministischer Code (siehe oben)
templates/report.html.j2   Report-Layout
examples/                  ein echter Lauf zum Anschauen
tests/                     pytest, Hook-Test, Fixtures, fiktiver Beispiel-Lauf
docs/bauauftrag.md         der ursprüngliche Bauauftrag inkl. Nachträgen
docs/testlauf-*.md         Protokolle der Testläufe: Zeitleiste, Fehler, Erkenntnisse
data/, runs/               Kennzahlen-Cache und Läufe (nicht versioniert)
```

## Grundregeln

- **Zahl-Objekt:** `{"wert", "einheit", "typ": "berichtet"|"schaetzung", "quelle" | "begruendung", "abgerufen"}` – `berichtet` braucht eine URL, `schaetzung` eine Begründung. Fehlende Werte bleiben `null`, nie aufgefüllt.
- **Im Report stehen Zahlen nur als Verweis** `{ref:<datei>#<json-pointer>}`; der Renderer setzt Wert, „~“ für Schätzungen und Fußnote ein. `validate.py` prüft jeden Verweis.
- **Datei-Eigentum:** Jeder Agent schreibt nur seine eigene Datei. Der Lektor ändert keine Originale, sondern liefert `lektorat.json`; der Code prüft, dass die Zahlenverweise exakt gleich bleiben.
- **Keine Anlageberatung**, keine Namen, Logos oder Markenelemente realer Asset Manager.

## Wenn etwas hakt

| Symptom | Ursache / Lösung |
|---|---|
| Lead meldet „Task-Tools fehlen“ | `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` fehlt (steht in `.claude/settings.json`; auf Opus 5 & Co. sind die Task-Tools sonst aus). Session neu starten. |
| Teammate meldet `No such tool: TaskUpdate/SendMessage` | Rollen brauchen diese Tools explizit in `tools:` (Split-Pane-Teammates bekommen sie nicht automatisch). Ist in den Rollen enthalten; bei eigenen Rollen ergänzen. |
| Lead wartet und startet keine weiteren Teammates | Mit `TaskList` prüfen; „starte firma-2 bis firma-4“ schreiben. Das Drehbuch verbietet erfundene Wartebedingungen, ältere Läufe hatten das Problem. |
| Kandidat ausgeschlossen: „unbekannter Ticker“ | Ticker in `kette.json` stimmt nicht (Börsensuffix `.DE`, `.SW`, `.T` …). Das ist Absicht: Der Code kontrolliert die Agenten. |
| EV/Umsatz fehlt bei einer Firma | Yahoo lieferte einen unplausiblen Wert (negativ oder Faktor 3 neben Marktkapitalisierung/Umsatz); `kennzahlen.py` verwirft ihn mit Hinweis statt ihn zu zeigen. |
| Türsteher lehnt ab, Agent diskutiert | Normal. Rollen sagen: korrigieren, nicht diskutieren. Die Fehlerliste steht in `gate-log.jsonl`. |
| Rückfragen der Teammates blockieren den Lead | Auto-Modus oder `acceptEdits`; fehlende Freigaben in `.claude/settings.json` ergänzen. |
| Teammates lassen sich am Ende nicht beenden | tmux-Panes von Hand schließen (`tmux kill-session -t <name>`). Betrifft Teammates, die vor einer Änderung der Rollen gestartet wurden. |

Mehr Details, inklusive einer minutengenauen Zeitleiste und aller Fehler des ersten Laufs: `docs/testlauf-2026-09-18.md`.

## Lizenz

MIT, siehe `LICENSE`.
