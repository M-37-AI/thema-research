# Bühne – Live-Fenster für einen Lauf

Stand: 2026-09-20. Baustein C aus dem Brainstorming vom 2026-09-20 (Reihenfolge: C Bühne, A Quellen-Leser, B Wächter).

## Zweck

Ein Browser-Fenster, das während eines `/thema`-Laufs live zeigt, was jeder Agent des Teams tut – als Raster von Karten, an tmux angelehnt, aber lesbar und filmbar. Zielgruppe: der Nutzer beim Zuschauen und die Zuschauer des YouTube-Videos. Die Bühne ist ein reines Anzeige-Werkzeug: Sie liest, sie ändert nichts am Lauf, sie braucht keine Änderung an Rollen, Drehbuch oder Hooks.

Nicht-Ziele: kein Fluss-Diagramm der Pipeline als Hauptbild, keine Steuerung der Agenten, kein Ersatz für tmux (die Agenten laufen weiter dort), keine Kostenabrechnung auf den Cent (Listenpreise, Näherung).

## Datenquellen

Alles Lesen, nichts Schreiben. Drei Quellen:

1. **Transkripte** unter `~/.claude/projects/<projekt-slug>/*.jsonl` (bzw. `$CLAUDE_CONFIG_DIR/projects/…`). Der Projekt-Slug ist der absolute Projektpfad mit jedem Zeichen außer `[A-Za-z0-9]` durch `-` ersetzt (so wie Claude Code ihn bildet; bei Bedarf über `cwd` in den Zeilen gegenprüfen).
   - **Lead:** Zeilen ohne `agentName`. Standard: das zuletzt geänderte Transkript ohne `agentName`, dessen `cwd` im Projektordner liegt. Optional fest per `--lead <session-id>`.
   - **Teammates:** alle Transkripte, deren Zeilen `teamName == "session-<lead-session-id>"` tragen. `agentName` ist der Name der Karte (z. B. `firma-3`, `red-team`).
   - Je Zeile relevant: `type` (`assistant`, `user`, `system`, sonst ignorieren), `timestamp`, `message.model`, `message.content[]` (Blöcke `text`, `thinking`, `tool_use`, `tool_result`), `message.usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cache_creation.ephemeral_5m_input_tokens`, `cache_creation.ephemeral_1h_input_tokens`), `wireToolInputs` (vollständige Tool-Eingaben, falls `tool_use.input` gekürzt ist).
   - Tool-Ergebnisse stehen in `user`-Zeilen als `tool_result`-Block; `toolUseResult` enthält strukturierte Daten (z. B. `stdout`). Teammate-Nachrichten stehen als `user`-Text `<teammate-message teammate_id="…">…</teammate-message>`; Türsteher-Rückmeldungen als `user`-Text, der mit `TaskCompleted hook feedback:` beginnt.
2. **`runs/<lauf>/gate-log.jsonl`**: eine Zeile je Türsteher-Entscheidung mit `zeit`, `entscheidung` (`akzeptiert`|`abgelehnt`), `grund`, `teammate`, `datei`, `fehler[]`, `task_subject`.
3. **Lauf-Ordner** `runs/<lauf>/`: `lauf.json` (Thema, Datum, gestartet) und die Existenz der Ergebnisdateien für die Phase.

Neue Transkripte werden alle 2 s gesucht; bestehende alle 150 ms fortgelesen. Halb geschriebene Zeilen (ohne abschließendes `\n`) bleiben liegen bis zum nächsten Durchlauf.

## Ereignismodell

`buehne_modell.py` wandelt jede Transkriptzeile in null oder mehr **Ereignisse** um. Ein Ereignis ist ein Dict:

```
{"zeit": "<ISO>", "agent": "<agentName oder 'lead'>", "art": <Art>, ...}
```

Arten und Zusatzfelder:

| Art | Aus | Felder |
|---|---|---|
| `text` | `assistant`/`text` | `text` (auf 600 Zeichen gekürzt) |
| `denkt` | `assistant`/`thinking` | – (nur Zustandswechsel, kein Inhalt) |
| `werkzeug` | `assistant`/`tool_use` | `werkzeug` (Name), `titel` (Klartext, z. B. `Sucht: Robotik Marktgröße 2030`), `detail` (Befehl/Pfad/Query, 200 Zeichen), `tool_use_id` |
| `ergebnis` | `user`/`tool_result` | `tool_use_id`, `fehler` (bool aus `is_error`), `auszug` (erste 200 Zeichen) |
| `nachricht` | `user`-Text `<teammate-message …>` | `von` (teammate_id), `text` (300 Zeichen) |
| `tuersteher_rueckmeldung` | `user`-Text `TaskCompleted hook feedback:` | `text` (300 Zeichen) |
| `verbrauch` | `assistant` mit `usage` | `modell`, `input`, `output`, `cache_lesen`, `cache_schreiben_5m`, `cache_schreiben_1h`, `kosten_usd` |
| `tuersteher` | gate-log | `entscheidung`, `datei`, `grund`, `fehler[]` (max. 5), `task_subject` |

`system`-Zeilen, `attachment`, `agent-setting` usw. erzeugen keine Ereignisse.

**Klartext für Werkzeuge** (`titel`): `WebSearch` → `Sucht: <query>`; `WebFetch` → `Liest: <host><pfad gekürzt>`; `Read` → `Liest: <datei>`; `Write`/`Edit` → `Schreibt: <datei>`; `Bash` → `Führt aus: <description oder erste Zeile>`; `TaskUpdate` mit `status: completed` → `Meldet fertig: #<taskId>`; `TaskUpdate` sonst → `Aufgabe #<taskId>: <status>`; `TaskList`/`TaskGet` → `Schaut in die Aufgabenliste`; `SendMessage` → `Schreibt an <to>`; `Agent` → `Startet <name> (<subagent_type>)`; sonst `<Name>`. Pfade werden relativ zum Projekt gekürzt.

## Kartenzustand

Je Agent hält der Zustand:

```
{"name", "rolle", "modell", "zustand", "zustand_seit", "aufgabe", "aktuell",
 "strom": [<letzte 40 Ereignisse ohne 'verbrauch'>],
 "tokens": {"input", "output", "cache_lesen", "cache_schreiben"},
 "kosten_usd", "schritte", "tuersteher": {"akzeptiert": n, "abgelehnt": n, "letzte": <Ereignis|null>},
 "gestartet", "zuletzt"}
```

- **rolle** aus dem Namen: `lead` bleibt `lead`; sonst Präfix bis zur ersten Ziffer-/Suffix-Gruppe, gegen die Rollen in `.claude/agents/*.md` geprüft (`firma-3-2` → `firma`, `red-team-bio` → `red-team`, `markt-2` → `markt`). Unbekanntes Präfix → Rolle `sonstige`.
- **zustand** (Ableitung aus dem jeweils letzten Ereignis): `denkt` → `denkt`; `werkzeug` → `werkzeug` (mit `aktuell` = Titel); `ergebnis` → bleibt `werkzeug`, bis das nächste `text`/`denkt` kommt; `text` → `schreibt`; `werkzeug` `TaskUpdate completed` → `wartet_tuersteher`, bis ein `tuersteher`-Ereignis oder eine `tuersteher_rueckmeldung` für diesen Agenten eintrifft; kein Ereignis seit 90 s → `untaetig`; Zeile `<teammate-message …>` mit „beende dich“ vom Lead oder kein Ereignis seit 10 min → `fertig`. Die Schwellen sind Konstanten am Dateianfang.
- **aufgabe**: der zuletzt gesehene Aufgabentitel `[runs/…] …` aus Teammate-Nachrichten (`task_assignment`) oder aus `TaskUpdate`-Ergebnissen; sonst aus dem ersten Spawn-Prompt (`Deine Aufgabe: [...]`).
- **kosten_usd**: Summe je `verbrauch`-Ereignis nach `tools/preise.json`: `input × p.input + output × p.output + cache_lesen × p.cache_lesen + cache_5m × p.cache_schreiben_5m + cache_1h × p.cache_schreiben_1h`, alles in USD pro Million Tokens. Unbekanntes Modell: 0 USD und `preis_unbekannt: true` auf der Karte.

`tools/preise.json` (Listenpreise, Stand 2026-09-19, dieselben Werte wie in `docs/testlauf-2-2026-09-19.md`):

| Modell-ID | input | output | cache_lesen | cache_schreiben_5m | cache_schreiben_1h |
|---|---|---|---|---|---|
| `claude-fable-5-1` | 10 | 50 | 0.25 | 12.5 | 20 |
| `claude-opus-5` | 5 | 25 | 0.5 | 6.25 | 10 |
| `claude-sonnet-5` | 2 | 10 | 0.2 | 2.5 | 4 |
| `claude-haiku-4-5` | 1 | 5 | 0.1 | 1.25 | 2 |

Modell-IDs mit Datumssuffix werden auf den Präfix ohne Suffix abgebildet.

## Gesamtzustand

```
{"lauf": {"ordner", "thema", "slug", "datum", "gestartet"},
 "phase": <Phase>, "phasen": [7 Namen], "laufzeit_s", "kosten_usd", "tokens", 
 "tuersteher": {"akzeptiert", "abgelehnt"},
 "agenten": {name: Karte}, "reihenfolge": [Namen], "modus": "live"|"replay", "replay_faktor"}
```

**Phase** (deterministisch aus Gate-Log und Dateien im Lauf-Ordner, die höchste zutreffende gilt):

1. `Phase 1` – Lauf-Ordner existiert
2. `Screening` – `markt-groesse.json`, `treiber.json`, `kette.json` alle akzeptiert
3. `Deep Dives` – `shortlist.json` existiert
4. `Red Team` – alle `firmen/*.json` aus `shortlist.json` akzeptiert (oder `redteam.json` existiert)
5. `Report` – `redteam.json` akzeptiert
6. `Lektorat` – `report.json` akzeptiert
7. `Fertig` – `report.html` existiert

**Reihenfolge der Karten:** Lead, dann Rollen in Pipeline-Reihenfolge (`markt`, `treiber`, `kette`, `firma`, `red-team`, `lektor`, `sonstige`), innerhalb der Rolle nach Startzeit. Für Rollen, die laut Drehbuch noch kommen, zeigt die Seite graue Platzhalter (markt, treiber, kette, firma ×4, red-team, lektor), die beim Erscheinen des echten Agenten ersetzt werden.

## Server (`tools/buehne.py`)

Nur Standardbibliothek. Lauscht auf `127.0.0.1`, Port 8767 (Option `--port`).

```
python3 tools/buehne.py runs/<lauf> [--open] [--port 8767] [--lead <session-id>]
python3 tools/buehne.py runs/<lauf> --replay [--speed 10] [--open]
```

- `GET /` → `templates/buehne.html`
- `GET /api/state` → Gesamtzustand als JSON (Snapshot für den Start)
- `GET /api/events` → Server-Sent Events: `init` (Snapshot), dann je Änderung `agent` (eine Karte komplett), `lauf` (Kopfzeile: Phase, Kosten, Laufzeit, Türsteher-Zähler), `ereignis` (ein Stromereignis mit Agentname, damit die Seite nur anhängt). Alle 15 s ein Ping-Kommentar.
- Threads: ein Tailer je Transkript (Muster aus AgentView: Position merken, nur vollständige Zeilen), ein Tailer fürs Gate-Log, ein Sucher für neue Transkripte (2 s), ein Zähler für Laufzeit/Untätig-Schwellen (1 s). Ein Lock um den Zustand.
- **Replay**: liest alle Transkripte des Teams und das Gate-Log vollständig, mischt die Ereignisse nach `zeit`, spielt sie mit Faktor `--speed` ab (Pausen über 3 s werden auf 3 s gekappt, wie in AgentView). Danach `modus: "replay-ende"`. Das Team wird im Replay über `--lead` oder, ohne Angabe, über das Transkript mit dem passenden `cwd` und einem Zeitstempel nach `lauf.json.gestartet` bestimmt.
- `--open` öffnet den Standardbrowser mit `http://127.0.0.1:<port>/`.
- Fehlermeldungen deutsch, Exit-Codes: 0 ok, 1 Bedienfehler (Lauf-Ordner fehlt, kein Lead gefunden), 2 Port belegt.

## Seite (`templates/buehne.html`)

Eine Datei, kein Framework, keine externen Skripte, nur Systemschriften und optional eine Monospace-Schrift aus Google Fonts (Fallback: Systemmonospace). Dunkles Design mit Farb-Tokens auf `:root` (Hintergrund `#0b0f16`, Fläche `#131a24`, Linie `#243043`, Text `#e6edf5`, leise `#8b9bb0`, Akzente: Blau für Lead, je Rolle eine Farbe; Grün akzeptiert, Rot abgelehnt, Ocker wartet). Ziel: 1600×900 in einem Browserfenster ohne Scrollen bei bis zu 10 Karten; unter 1100 px Breite bricht das Raster auf 2 Spalten, unter 700 px auf 1 Spalte.

Aufbau:

- **Kopfzeile**: links Thema und Lauf-Ordner; Mitte die 7 Phasen als Schrittleiste (aktive Phase hell, erledigte mit Haken); rechts Laufzeit `mm:ss`, Kosten `≈ 12,40 $`, Türsteher `✓ 9 · ✗ 2`, Agentenzahl, Modus (LIVE / REPLAY ×10).
- **Raster**: CSS Grid, `repeat(auto-fill, minmax(360px, 1fr))`, Karten gleich hoch, das Raster füllt die Höhe.
- **Karte**: Kopf mit Farbpunkt (Rolle), Name, Modell-Kürzel (`Sonnet 5`), Zustandsring (Animation bei `denkt`/`werkzeug`, still bei `untaetig`/`fertig`), Zustandstext („sucht im Web“, „wartet auf Türsteher“). Zeile 2: Aufgabe (eine Zeile, gekürzt). Zeile 3: `aktuell` in Monospace. Mitte: der Strom, neueste unten, automatisch nachlaufend; Zeilen mit Symbol je Art (Text ohne Symbol, Werkzeug ›, Ergebnis ✓/✗, Nachricht ✉, Türsteher-Rückmeldung ⛔). Fuß: Tokens (`out 12,3k · cache 1,2M`), Kosten, Schritte, Türsteher-Zähler der Karte.
- **Türsteher-Blitz**: bei `tuersteher`-Ereignis bekommt die Karte 1,5 s einen roten oder grünen Rahmen und oben eine Zeile mit Datei und Grund; abgelehnt zeigt bis zu 3 Fehler.
- **Platzhalter**: graue Karte mit Rollenname und „wartet auf Start“.
- Klick auf eine Karte vergrößert sie auf 2 Spalten (Toggle), um im Video einen Agenten hervorzuheben. Taste `F` Vollbild.
- Verbindung: `EventSource('/api/events')`; bei Abbruch automatisches Wiederverbinden mit Snapshot aus `/api/state`.

## Fehlerfälle

| Fall | Verhalten |
|---|---|
| Lauf-Ordner fehlt | Meldung „Lauf-Ordner … existiert nicht. Erst /thema starten.“ Exit 1 |
| Kein Lead-Transkript | Meldung mit Hinweis auf `claude --teammate-mode tmux` im Projektordner und Option `--lead`. Exit 1 |
| Port belegt | Meldung mit Vorschlag `--port`. Exit 2 |
| Gate-Log fehlt | Bühne läuft ohne Türsteher-Anzeige, Phase nur aus Dateien |
| Unbekanntes Modell | Kosten 0, Karte zeigt „Preis unbekannt“ |
| Kaputte Transkriptzeile | überspringen, weiterlesen |
| Transkript wird gekürzt (Größe < Position) | von vorn lesen |

## Tests (`tests/test_buehne.py`, offline)

Fixtures unter `tests/fixtures/transkripte/`: gekürzte, anonymisierte Auszüge (je 10–20 Zeilen) für einen Lead und zwei Teammates (`markt`, `firma-1`) mit `text`, `thinking`, `tool_use` (WebSearch, Bash, TaskUpdate completed), `tool_result`, `usage`, Teammate-Nachricht und Türsteher-Rückmeldung; dazu ein Gate-Log mit einer Annahme und einer Ablehnung.

Geprüft wird:

- Zeile → Ereignisse: jede Art einmal, Kürzung der Texte, `wireToolInputs` hat Vorrang.
- Rollen-Zuordnung (`firma-3-2`, `red-team-bio`, `markt-2`, `lead`, `unbekannt-1`).
- Kosten: bekanntes Modell auf den Cent gegen Handrechnung; Datumssuffix; unbekanntes Modell → 0 und Flag.
- Zustandsautomat: Folge `denkt → werkzeug → ergebnis → text → TaskUpdate completed → tuersteher` ergibt die erwarteten Zustände; Untätig-Schwelle mit injizierter Uhr.
- Phase aus Gate-Log und Dateien für die Fixture `tests/fixtures/beispiel-lauf` (erwartet `Fertig`) und für einen leeren Lauf-Ordner (`Phase 1`).
- Team-Erkennung: aus einem temporären Projekt-Ordner mit drei Transkripten wird der Lead und die zwei Teammates gefunden.
- Replay-Mischung: Ereignisse aus mehreren Quellen sind nach `zeit` sortiert.
- Snapshot ist JSON-serialisierbar und enthält alle Pflichtfelder.

Der Server selbst wird per Smoke-Test geprüft: Start auf einem freien Port gegen die Fixtures, `GET /api/state` liefert 200 und gültiges JSON, dann Stop. Die Optik wird manuell per Headless-Brave-Screenshot gegen `examples/batterierecycling-2026-09-19` im Replay geprüft (die zugehörigen Transkripte liegen lokal beim Nutzer; das Repo enthält sie nicht).

## Dokumentation

- README: Abschnitt „Zuschauen: die Bühne“ nach „Einen Lauf starten“ mit Aufruf, Screenshot-Verweis und Replay.
- README-Tabelle der Tools: Zeile für `tools/buehne.py`.
- CLAUDE.md bleibt unverändert (Agenten brauchen die Bühne nicht zu kennen).

## Dateien

```
tools/buehne.py            Server, CLI, Tailer, Replay
tools/buehne_modell.py     reine Funktionen: Ereignisse, Karten, Phase, Kosten, Rollen
tools/preise.json          Listenpreise je Modell
templates/buehne.html      die Seite
tests/test_buehne.py
tests/fixtures/transkripte/lead.jsonl, markt.jsonl, firma-1.jsonl, gate-log.jsonl
docs/superpowers/specs/2026-09-20-buehne-design.md   (dieses Dokument)
```
