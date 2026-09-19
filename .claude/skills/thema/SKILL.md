---
name: thema
description: Startet einen Thematic-Research-Lauf mit dem Agenten-Team – vom Trend zum fertigen Report. Nur manuell per /thema <trend> aufrufen.
argument-hint: "[trend, z. B. robotik]"
disable-model-invocation: true
---

# Drehbuch: Thematic Research zu „$ARGUMENTS“

## 0. Deine Rolle
Du bist **Lead**. Du recherchierst und schreibst keine Analysen selbst – du koordinierst, prüfst und entscheidest. Einzige Ausnahmen: `lauf.json`, `shortlist.json` und `report.json`.
**Warte auf deine Teammates.** Wenn ein Teammate fertig ist, bekommst du automatisch eine Nachricht; du musst nicht nachfragen. Übernimm nie die Aufgabe eines Teammates, auch wenn es lange dauert – frag im Zweifel per `SendMessage` nach dem Stand.

**Warte nur auf Ereignisse, die sicher eintreten:** eine Aufgabe wird erledigt, ein Teammate meldet sich idle. Erfinde keine Zwischenschritte wie „melde dich, wenn du deine erste Aufgabe genommen hast“ – Teammates arbeiten einfach weiter, und du wartest dann auf eine Nachricht, die nie kommt. Ob Aufgaben in Arbeit sind, siehst du jederzeit mit `TaskList`. Halte dich an das Drehbuch, auch wenn früher im Lauf etwas schiefging.

Teammates kennen deinen Verlauf nicht. **Jeder Spawn-Prompt enthält Thema und Lauf-Ordner** und nennt die Aufgabe.

## 1. Lauf anlegen
- Slug aus „$ARGUMENTS“: klein, ASCII (ä→ae, ö→oe, ü→ue, ß→ss), Leerzeichen → Bindestrich. Datum: `date +%F`.
- Lauf-Ordner `runs/<slug>-<datum>/` mit `mkdir -p runs/<slug>-<datum>/firmen`.
- `lauf.json` schreiben: `{"thema": "<Thema, lesbar>", "slug": "<slug>", "datum": "<datum>", "gestartet": "<ISO-Zeitstempel>"}` (Zeitstempel: `date -Iseconds`).

## 2. Phase 1 – Markt und Potenzial
Lege drei Aufgaben an (Titel exakt nach Konvention):
- `[runs/<lauf>/markt-groesse.json] Marktgröße`
- `[runs/<lauf>/treiber.json] Treiber und Hürden`
- `[runs/<lauf>/kette.json] Wertschöpfungskette`

Spawne drei Teammates mit dem **Agent-Tool**, jeweils mit `name` und dem gleichnamigen Agent-Typ (`subagent_type`): `markt`, `treiber`, `kette`. Weise jedem seine Aufgabe zu. Spawn-Prompt z. B.:
> Thema: <Thema>. Lauf-Ordner: runs/<lauf>/. Deine Aufgabe: [runs/<lauf>/kette.json] Wertschöpfungskette. Arbeite nach deiner Rollenbeschreibung und CLAUDE.md, markiere die Aufgabe als erledigt, wenn validate.py ✓ meldet.

Warte, bis alle drei Aufgaben erledigt sind.

## 3. Screening und Shortlist
1. `python3 tools/merge_markt.py runs/<lauf>`
2. `python3 tools/screen.py runs/<lauf>` – zeige dem Nutzer die Universum-Tabelle.
3. Wähle **6–8 Firmen**. Der `shortlist_vorschlag` ist ein Ausgangspunkt, keine Vorgabe. Achte auf **Abdeckung der Segmente** statt nur auf bekannte Namen und hohe Scores; mindestens die Hälfte der Segmente soll vertreten sein.
4. Schreibe `runs/<lauf>/shortlist.json`:
   ```json
   {"auswahl": [{"ticker": "…", "name": "…", "segment_id": "…", "begruendung": "…"}],
    "abweichungen_vom_vorschlag": "Welche Vorschläge du ersetzt hast und warum"}
   ```

## 4. Phase 2 – Deep Dives
- Lege pro Firma eine Aufgabe an: `[runs/<lauf>/firmen/<TICKER>.json] Deep Dive <Name>`.
- Spawne **alle vier Teammates auf einmal** (nicht erst einen zur Probe) vom Typ `firma` mit den Namen `firma-1` … `firma-4`. Sie nehmen sich die Aufgaben selbst aus der Liste – weise nichts zu. Spawn-Prompt: Thema, Lauf-Ordner, „Nimm dir freie Deep-Dive-Aufgaben aus der Aufgabenliste, eine nach der anderen, bis keine mehr frei ist.“

## 5. Red Team
- Lege `[runs/<lauf>/redteam.json] Red Team` an, **blockiert durch alle Deep-Dive-Aufgaben** (Abhängigkeit per `TaskUpdate`/`addBlockedBy`).
- Spawne `red-team` (Typ `red-team`) mit Thema, Lauf-Ordner und der Aufgabe. Es darf den Teammates Rückfragen stellen.
- Warte, bis die Red-Team-Aufgabe erledigt ist.

## 6. Report
- Lege `[runs/<lauf>/report.json] Report` an – auch deine eigene Datei geht durch den Türsteher.
- Schreibe `runs/<lauf>/report.json` nach dem Skill **report-stil**. Zahlen ausschließlich als `{ref:<datei>#<json-pointer>}`.
- **Jeder Einwand mit `schwere: hoch`** aus `redteam.json` bekommt einen Eintrag in `antworten_auf_einwaende` (`einwand_ref`, `antwort`, `konsequenz`).
- `python3 tools/validate.py runs/<lauf>/report.json`, bis ✓ (Warnungen zu ausgeschriebenen Zahlen beheben). Dann die Aufgabe als erledigt markieren.

## 7. Lektorat
- Lege `[runs/<lauf>/lektorat.json] Lektorat` an und spawne `lektor` (Typ `lektor`) mit Lauf-Ordner und Aufgabe. Er überarbeitet die Sprache aller Texte, die im Report erscheinen, für interessierte Laien – Inhalt und Zahlen bleiben gleich.
- Du änderst in dieser Zeit nichts mehr an den Dateien des Laufs. Warte, bis die Aufgabe erledigt ist.
- Dann: `python3 tools/render.py runs/<lauf> --open` (setzt das Lektorat ein) und zum Vergleich `python3 tools/render.py runs/<lauf> --ohne-lektorat`.

## 8. Abschluss
Kurze Meldung an den Nutzer:
- **Dauer** (von `gestartet` in `lauf.json` bis jetzt),
- **Anzahl der Aufgaben** (erledigt / gesamt),
- **Türsteher:** Ablehnungen aus `runs/<lauf>/gate-log.jsonl` (Anzahl, welche Dateien, häufigste Fehler),
- Pfad zum Report. Dann die Teammates bitten, sich zu beenden.
- Bitte den Nutzer, `/cost` einzugeben – das kann nur er, und die Zahl gehört zur Auswertung des Laufs.
