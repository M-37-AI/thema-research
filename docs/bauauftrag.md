# Bauauftrag: Thematic-Research-Team mit Claude Code

> **Historisches Dokument.** So lautete der ursprüngliche Auftrag; die Nachträge am Ende halten fest, wo die Umsetzung bewusst abweicht (u. a. Python-venv, Referenz-Syntax, Lektor-Agent, Exhibits ohne Plotly). Den aktuellen Stand beschreibt die README.

Du baust in diesem leeren Repository ein Projekt, mit dem ein Team aus Claude-Code-Agenten einen Investment-Trend (z. B. „Robotik") recherchiert und daraus einen Thematic-Research-Report im Stil eines institutionellen Asset Managers erzeugt. Ein Lauf wird später mit `/thema robotik` gestartet.

Das Projekt wird in einem YouTube-Tutorial gezeigt. Baue es deshalb in sechs Stufen und halte nach jeder Stufe an (siehe „Arbeitsweise").

## Leitprinzipien

1. **Die KI urteilt, der Code kontrolliert.** Datenabruf, Screening, Zusammenführen, Validierung und Rendering sind deterministischer Python-Code. Agenten recherchieren, bewerten und schreiben.
2. **Keine Zahl ohne Herkunft.** Jede Zahl ist ein Zahl-Objekt (Stufe 1). Schätzungen sind erlaubt, müssen aber als Schätzung markiert und begründet sein.
3. **Agenten liefern JSON nach Schema, keinen Fließtext.** Jeder Agent schreibt ausschließlich seine eigene Datei.
4. **Keine Anlageberatung.** Keine Kauf- oder Verkaufsempfehlungen, keine Kursziele. Keine Namen, Logos oder Markenelemente realer Asset Manager.

## Arbeitsweise

- Arbeite Stufe für Stufe. Nach jeder Stufe: kurze Zusammenfassung, was entstanden ist, der Befehl, mit dem ich es teste – dann anhalten und auf mein OK warten.
- Python 3.11+, Abhängigkeiten in `requirements.txt` (yfinance, jsonschema, jinja2, plotly, pandas). Keine API-Keys, keine Datenbank, kein Web-Server.
- Jedes Skript unter `tools/` ist einzeln aufrufbar, hat `--help`, gibt verständliche deutsche Fehlermeldungen aus und endet mit einem sinnvollen Exit-Code.
- Kommentare und Texte auf Deutsch; Dateinamen und JSON-Schlüssel ohne Umlaute.
- Wenn du dir bei einer Claude-Code-Funktion (Hooks, Agent Teams, Subagents, Skills, Permissions) nicht sicher bist, lies die aktuelle Doku unter https://code.claude.com/docs, statt zu raten.

## Zielstruktur

```
thema-research/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── .claude/
│   ├── settings.json
│   ├── agents/          markt.md, treiber.md, kette.md, firma.md, red-team.md
│   └── skills/
│       ├── thema/SKILL.md
│       └── report-stil/SKILL.md
├── schemas/             zahl, markt-groesse, treiber, kette, markt, firma, redteam, report
├── tools/               validate, kennzahlen, merge_markt, screen, bottom_up, gate, gate_create, render
│   └── screen_regeln.json
├── templates/report.html.j2
├── data/                cache/, kennzahlen/
├── runs/                ein Ordner pro Lauf: <thema-slug>-<YYYY-MM-DD>/
└── tests/               fixtures/gut, fixtures/kaputt, fixtures/beispiel-lauf, test_gate.sh
```

---

## Stufe 1 – Verträge (`schemas/`, `tools/validate.py`)

**Zahl-Objekt** (`schemas/zahl.schema.json`), verwendet in allen anderen Schemas:

| Feld | Pflicht | Inhalt |
|---|---|---|
| `wert` | ja | number oder null |
| `einheit` | ja | z. B. „Mrd USD", „% Umsatz", „%" |
| `typ` | ja | `berichtet` oder `schaetzung` |
| `quelle` | bei `berichtet` | URL |
| `abgerufen` | ja | ISO-Datum |
| `begruendung` | bei `schaetzung` | Herleitung in 1–3 Sätzen |
| `jahr`, `herausgeber` | optional | Bezugsjahr, Urheber der Zahl |

Setze die bedingten Pflichtfelder mit `if/then` um.

**Weitere Schemas:**

- `markt-groesse`: `thema`, `schaetzungen` (mindestens 3) mit je `herausgeber`, `jahr_prognose`, `marktgroesse` (Zahl), optional `cagr` (Zahl) und `abgrenzung` (was zählt zum Markt).
- `treiber`: `treiber` und `huerden` (je mindestens 3) mit `titel`, `beschreibung`, `belege` (Liste aus Zahl-Objekten oder `{aussage, quelle}`).
- `kette`: 5–8 `segmente` mit `id`, `name`, `beschreibung`, optional `marktgroesse` (Zahl), `margenprofil` (`hoch|mittel|niedrig`) plus `begruendung`, `kandidaten` (3–6) mit `name`, `ticker` (yfinance-Notation inkl. Börsensuffix), `begruendung`.
- `markt`: zusammengeführtes Ergebnis aus den drei obigen plus `thema` und `datum`.
- `firma`: `name`, `ticker`, `segment_id`, `geschaeftsmodell`, `themen_exposure` (Zahl, Einheit „% Umsatz"), `kennzahlen_datei`, `wettbewerbsposition`, `rolle_im_thema` (`Kernprofiteur|Zulieferer|Mitlaeufer`), `ueberzeugung` (`hoch|mittel|niedrig`) plus `begruendung`, `bull_case` (≥ 2), `bear_case` (≥ 2), `was_uns_widerlegen_wuerde`.
- `redteam`: `einwaende` mit `ziel` (Datei + JSON-Pfad), `einwand`, `schwere` (`hoch|mittel|niedrig`), optional `beleg`; dazu `bottom_up_kommentar` und `gesamturteil`.
- `report`: `titel`, `kernaussage` (max. 2 Sätze), `these`, `abschnitte` (`markt`, `treiber_und_huerden`, `wertschoepfung`, `unternehmen`, `risiken`), `antworten_auf_einwaende` mit `einwand_ref`, `antwort`, `konsequenz`, dazu `beobachtungspunkte` (3–5).

**`tools/validate.py <datei...>`** wählt das Schema anhand des Dateinamens (Dateien in `firmen/` → `firma`). Zusätzlich prüft es rekursiv jedes Objekt mit dem Schlüssel `wert` gegen das Zahl-Schema. Fehler werden mit JSON-Pfad ausgegeben, z. B. `segmente[2].marktgroesse: quelle fehlt (typ=berichtet)`. Exit 0 = gültig, 1 = Fehler.

**Fixtures:** `tests/fixtures/gut/` (je Schema eine gültige Datei) und `tests/fixtures/kaputt/` mit typischen Fehlern: Zahl ohne Quelle, Schätzung ohne Begründung, falscher Enum-Wert, zu wenige Schätzungen.

**Test:** `python3 tools/validate.py tests/fixtures/gut/*.json` → alles grün; `python3 tools/validate.py tests/fixtures/kaputt/*.json` → verständliche Fehlerliste.

---

## Stufe 2 – Werkzeuge (`tools/`)

- **`kennzahlen.py TICKER [...] [--offline]`**: holt per yfinance Name, Währung, Marktkapitalisierung, Umsatz TTM, Umsatzwachstum YoY, Bruttomarge, operative Marge, EV/Umsatz und KGV. Jeder Wert ist ein Zahl-Objekt (`typ: berichtet`, `quelle: https://finance.yahoo.com/quote/<TICKER>`). Zusätzlich `umsatz_ttm_usd`, umgerechnet über yfinance-FX-Kurse; der Kurs selbst wird ebenfalls als Zahl-Objekt gespeichert. Fehlende Werte werden `null` mit Hinweis und niemals aufgefüllt. Ergebnisse gehen nach `data/kennzahlen/<TICKER>.json`, Rohdaten in einen Cache unter `data/cache/`; `--offline` liest nur den Cache. Ein unbekannter Ticker erzeugt eine klare Meldung und bricht die übrigen nicht ab.
- **`merge_markt.py <lauf>`**: führt `markt-groesse.json`, `treiber.json` und `kette.json` zu `markt.json` zusammen und validiert das Ergebnis.
- **`screen.py <lauf>`**: liest alle Kandidaten aus `markt.json`, ruft die Kennzahlen ab (per Import, nicht als Subprozess) und wendet die Regeln aus `tools/screen_regeln.json` an (Mindest-Marktkapitalisierung, Datenvollständigkeit, keine Duplikate). Es schreibt `universum.json`, in dem jeder Kandidat den Status `aufgenommen` oder `ausgeschlossen` samt Grund hat, dazu einen transparenten Score (Formel in der Regeldatei dokumentiert) und einen `shortlist_vorschlag` mit 8–10 Firmen. Im Terminal erscheint eine gut lesbare Tabelle.
- **`bottom_up.py <lauf>`**: berechnet über alle `firmen/*.json` die Summe aus `umsatz_ttm_usd × themen_exposure` und vergleicht sie mit der Spanne der Top-down-Schätzungen. Ausgabe ist `bottom_up.json` inklusive Abdeckungsquote, klar als Näherung gekennzeichnet (nur Shortlist, Schätzungen fließen ein).

**Test:** `python3 tools/kennzahlen.py NVDA ABBN.SW 6954.T` (drei Börsen, drei Währungen), danach dasselbe mit `--offline`.

---

## Stufe 3 – Türsteher (Hooks)

- **`gate.py`** (Hook `TaskCompleted`): liest das Hook-JSON von stdin (`task_subject`, `task_description`, `teammate_name`, `cwd`, …). Es sucht im `task_subject` (ersatzweise in der `task_description`) nach einem Pfad der Form `[runs/….json]`.
  - Kein Pfad → Exit 0.
  - Datei fehlt → Meldung auf stderr, Exit 2.
  - Validierungsfehler → Fehlerliste plus „Korrigiere die Datei und markiere die Aufgabe erneut als erledigt." auf stderr, Exit 2.
  - Jede Entscheidung (akzeptiert/abgelehnt, Teammate, Datei, Fehleranzahl, Zeitstempel) wird an `runs/<lauf>/gate-log.jsonl` angehängt. Der Report zeigt daraus später eine Türsteher-Statistik.
- **`gate_create.py`** (Hook `TaskCreated`): Jeder Aufgabentitel muss `[runs/….json]` enthalten, außer er beginnt mit `Koordination:`. Sonst folgt Exit 2 mit einem Hinweis auf die Konvention.
- **`.claude/settings.json`**:
  - `env`: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
  - Hooks für `TaskCompleted` und `TaskCreated`, Befehle über `"$CLAUDE_PROJECT_DIR"/tools/...`
  - Permissions: WebSearch, WebFetch, das Ausführen von `python3 tools/...` sowie Dateiänderungen in `runs/` und `data/` vorab erlauben, weil sonst jede Berechtigungsanfrage der Teammates beim Lead landet. Verwende die aktuelle Syntax laut Doku.

**Test:** `tests/test_gate.sh` schickt Beispiel-Hook-JSON an beide Skripte und prüft die Exit-Codes: gültige Datei → 0, kaputte → 2, fehlende → 2, kein Pfad → 0, Aufgabe ohne Konvention → 2.

---

## Stufe 4 – Rollen (`.claude/agents/`)

Lege fünf Subagent-Definitionen an. Sie werden später als Teammate-Typen verwendet. Jede Definition hat Frontmatter mit `name`, `description`, `tools` und `model`. Der Text ist immer gleich gegliedert: **Rolle – Input – Output (Datei + Schema) – Arbeitsregeln – Fertig, wenn**.

Gemeinsame Regeln stehen in `CLAUDE.md` und werden in den Definitionen nur referenziert. Sie lauten: Zahl-Objekte verwenden, nur die eigene Datei schreiben, vor dem Abschließen selbst `validate.py` laufen lassen. Eine Ablehnung durch den Türsteher wird korrigiert, nicht diskutiert. Quellen nach Qualität: Geschäftsberichte und Behörden vor Verbänden vor Studien mit Methodik vor Pressemitteilungen von Marktforschern (Letztere nur mit Hinweis).

| Name | Tools | Modell | Auftrag | Output |
|---|---|---|---|---|
| `markt` | Read, Write, WebSearch, WebFetch, Bash | sonnet | Mindestens 3 unabhängige Marktschätzungen; unterschiedliche Marktabgrenzungen explizit machen; nicht mitteln. | `markt-groesse.json` |
| `treiber` | Read, Write, WebSearch, WebFetch, Bash | sonnet | Treiber und Hürden (Technik, Kostenkurven, Arbeitsmarkt, Regulierung …), jeweils mit Beleg. | `treiber.json` |
| `kette` | Read, Write, WebSearch, WebFetch, Bash | sonnet | 5–8 Segmente mit börsennotierten Kandidaten und korrekten yfinance-Tickern, ausdrücklich auch weniger bekannte Zulieferer. | `kette.json` |
| `firma` | Read, Write, WebSearch, WebFetch, Bash | sonnet | Genau eine Firma pro Aufgabe. Zuerst `kennzahlen.py`, dann Exposure aus der Segmentberichterstattung mit Quelle, sonst Schätzung mit Begründung. | `firmen/<TICKER>.json` |
| `red-team` | Read, Write, WebSearch, WebFetch, Bash | opus | Führt `bottom_up.py` aus und greift Prognosen an (Spanne, Herausgeber, Interessenkonflikte), ebenso Exposure-Behauptungen, Etikettenschwindel und fehlende Gegenbelege. Darf einzelnen Teammates vor dem Urteil direkt Rückfragen schicken. Mindestens 3 Einwände zum Markt und 1 pro Firma. | `redteam.json` |

---

## Stufe 5 – Orchestrierung (`CLAUDE.md`, Skills)

**`CLAUDE.md`** (kurz halten, unter 80 Zeilen, denn jeder Teammate lädt sie) enthält:

- Projektziel in drei Sätzen
- Ordnerkonvention `runs/<thema-slug>-<YYYY-MM-DD>/`
- Regeln zum Zahl-Objekt
- Datei-Eigentum: jeder Agent schreibt nur seine eigene Datei
- Aufgabenkonvention `[runs/…/datei.json] Titel`
- Teammate-Namen: `markt`, `treiber`, `kette`, `firma-1` … `firma-4`, `red-team`
- Keine Anlageberatung

**`.claude/skills/thema/SKILL.md`** hat im Frontmatter `name: thema`, eine Beschreibung und `disable-model-invocation: true`. Der Text ist das Drehbuch für den Lead mit `$ARGUMENTS` als Thema:

0. Du bist Lead. Du recherchierst und schreibst keine Analysen selbst, du koordinierst, prüfst und entscheidest. Warte auf deine Teammates.
1. Lege den Lauf-Ordner und `lauf.json` (Thema, Datum) an.
2. **Phase 1:** Lege drei Aufgaben nach Konvention an. Spawne die Teammates `markt`, `treiber` und `kette` mit dem gleichnamigen Agent-Typ. Jeder Spawn-Prompt enthält Thema und Lauf-Ordner, denn Teammates kennen deinen Verlauf nicht.
3. Wenn alle drei fertig sind: `merge_markt.py` und `screen.py` ausführen, die Universum-Tabelle zeigen und 6–8 Firmen auswählen. Achte dabei auf Abdeckung der Segmente statt nur auf bekannte Namen. Die Auswahl mit Begründung kommt nach `shortlist.json`.
4. **Phase 2:** Lege pro Firma die Aufgabe `[runs/…/firmen/<TICKER>.json] Deep Dive <Name>` an. Spawne vier Teammates vom Typ `firma`, die sich die Aufgaben selbst nehmen.
5. Lege die Red-Team-Aufgabe mit Abhängigkeit auf alle Firmen-Aufgaben an und spawne `red-team`.
6. Danach schreibst du `report.json` nach dem Skill `report-stil`. Jeder Einwand mit `schwere: hoch` wird in `antworten_auf_einwaende` beantwortet. Anschließend validieren und `render.py <lauf> --open` ausführen.
7. Zum Schluss eine kurze Abschlussmeldung: Dauer, Anzahl der Aufgaben, Ablehnungen durch den Türsteher.

**`.claude/skills/report-stil/SKILL.md`** braucht eine bewusst „drängende" Beschreibung, damit der Skill bei jedem Schreiben von Report-Texten greift. Er legt fest:

- nüchterner, institutioneller Ton aus der „Wir"-Perspektive des Research-Teams
- Kernaussage in höchstens 2 Sätzen
- Spannen statt Punktschätzungen
- jede Zahl mit Verweis auf ihr Zahl-Objekt
- zu jeder These ein „Was uns widerlegen würde"
- 3–5 Beobachtungspunkte
- keine Kaufempfehlungen, keine Namen realer Asset Manager

---

## Stufe 6 – Report & Probelauf

**`templates/report.html.j2` und `render.py <lauf> [--open]`** erzeugen eine einzige, in sich geschlossene HTML-Datei (Plotly inline, funktioniert offline). Das Design ist nüchtern-institutionell: weißer Hintergrund, eine Akzentfarbe, Serifen-Überschriften, serifenlose Fließtexte, viel Weißraum und nummerierte Fußnoten für alle Quellen. Schätzungen sind sichtbar markiert (z. B. „~" plus Fußnote „Schätzung").

Abschnitte:
1. Titel und Kernaussage
2. These
3. Markt – **Chart 1:** Spanne der Schätzungen als horizontale Bereichsbalken je Herausgeber
4. Treiber und Hürden
5. Wertschöpfungskette – **Chart 2:** Segmente mit ihren Firmen (z. B. Treemap)
6. Unternehmen – Tabelle (Name, Segment, Rolle, Exposure, Wachstum, Marge, EV/Umsatz, Überzeugung) und **Chart 3:** Streudiagramm Exposure gegen EV/Umsatz, Punktgröße = Marktkapitalisierung
7. Red Team und unsere Antworten
8. Bottom-up-Check
9. Beobachtungspunkte
10. Methodik inklusive Türsteher-Statistik aus `gate-log.jsonl`
11. Quellen
12. Hinweis „Keine Anlageberatung"

**`tests/fixtures/beispiel-lauf/`** ist ein vollständiger fiktiver Beispiel-Lauf mit klar erfundenen Firmen wie „Beispiel Robotik AG", sichtbar als fiktiv markiert. Damit lässt sich der Renderer ohne Agenten testen.

**`README.md`** enthält:
- Setup: venv und `pip install -r requirements.txt`
- Start eines Laufs: in iTerm2 oder tmux `claude --teammate-mode tmux`, dann `/thema robotik`
- den Hinweis, dass Agent Teams experimentell sind und deutlich mehr Tokens verbrauchen

**Test:** `python3 tools/render.py tests/fixtures/beispiel-lauf --open`

---

## Nicht-Ziele (für diese Version)

- keine Automatisierung oder Zeitplanung
- keine Web-Oberfläche
- keine Anbindung an ein Depot
- kein Branding realer Asset Manager
- keine Kauf- oder Verkaufssignale
---

## Nachtrag (vereinbart im Brainstorming, 2026-09-18): Referenz-Syntax im Report

Zahlen stehen in den Textfeldern von `report.json` nie ausgeschrieben, sondern als Verweis auf ihr Zahl-Objekt:

```
{ref:markt-groesse.json#/schaetzungen/0/marktgroesse}
{ref:firmen/NVDA.json#/themen_exposure}
```

- Pfad relativ zum Lauf-Ordner, Fragment ist ein JSON-Pointer (RFC 6901).
- **`validate.py`** (Schema `report`): findet alle Verweise und prüft, dass Datei existiert, Pointer auflöst und das Ziel ein gültiges Zahl-Objekt ist. Der Lauf-Ordner ist der Ordner der Report-Datei. Fehlermeldung z. B. `abschnitte.markt: Verweis firmen/XYZ.json#/themen_exposure nicht auflösbar (Datei fehlt)`.
- Ausgeschriebene Beträge im Text (z. B. „12 Mrd", „34 %") erzeugen eine **Warnung** (kein Fehler, Exit-Code bleibt 0).
- **`render.py`** ersetzt jeden Verweis durch den formatierten Wert (Schätzungen mit „~") plus nummerierte Fußnote (Quelle, Herausgeber, Abrufdatum). Gleiche Verweise teilen sich eine Fußnote.
- **Skill `report-stil`** schreibt diese Syntax als einzige erlaubte Zahlenschreibweise vor.

## Nachtrag: Umgebung

Python 3.12 in `.venv` (angelegt mit `uv venv --python 3.12 .venv`), weil das System-Python 3.9 ist. Alle Befehle `python3 tools/...` setzen ein aktiviertes venv voraus.

## Nachtrag: Exhibits ohne Plotly (2026-09-18)

Die Charts wurden nach dem Dataviz-Verfahren überarbeitet und sind jetzt reines SVG/HTML, das `render.py` selbst erzeugt – Plotly ist entfallen (Report ~0,1 statt ~5 MB, druckbar, ohne JavaScript lesbar; ein kurzes Skript ergänzt nur Tooltips).

- **Exhibit 1:** waagerechte Balken **ab null** (vorher ab der kleinsten Schätzung – irreführend), eine Farbe, Schätzungen heller + „~“, Abgrenzung am Balken.
- **Exhibit 2:** Treemap (gleich große Kacheln, Fläche ohne Bedeutung) ersetzt durch eine Tabelle mit Firmen-Kärtchen: ausgewählt / gescreent / ausgeschlossen.
- **Exhibit 4:** Streudiagramm mit validierter Palette (Slots 1–3 der Referenzpalette; die alte Marine/Blau/Grau-Kombination fiel bei Helligkeit und Sättigung durch), gleich große Punkte statt Blasen, Kurznamen statt Ticker.
