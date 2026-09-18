# Thematic-Research-Team

Ein Team aus Claude-Code-Agenten recherchiert einen Investment-Trend und erzeugt daraus einen Thematic-Research-Report im Stil eines institutionellen Asset Managers. Gestartet wird mit `/thema <trend>`. **Die KI urteilt, der Code kontrolliert:** Agenten recherchieren, bewerten und schreiben JSON; Python-Tools unter `tools/` rufen Daten ab, screenen, prüfen und rendern.

## Umgebung
- Das venv ist beim Start von `claude` bereits aktiv. Tools immer direkt aufrufen: `python3 tools/<tool>.py …` – ohne `source`, `cd` oder `&&` davor (sonst Rückfrage beim Lead).
- Jedes Tool hat `--help`.

## Ordner
- Ein Lauf = ein Ordner `runs/<thema-slug>-<YYYY-MM-DD>/` (Slug: klein, ASCII, Bindestriche, z. B. `robotik`, `humanoide-roboter`).
- Firmen-Deep-Dives: `runs/<lauf>/firmen/<TICKER>.json`. Kennzahlen: `data/kennzahlen/<TICKER>.json` (nur über `tools/kennzahlen.py`).
- Schemas: `schemas/*.schema.json`. Dateinamen und JSON-Schlüssel ohne Umlaute.

## Zahl-Objekt – keine Zahl ohne Herkunft
Jede Zahl in jeder Datei ist ein Zahl-Objekt (`schemas/zahl.schema.json`):
```json
{"wert": 42.5, "einheit": "Mrd USD", "typ": "berichtet", "quelle": "https://…", "abgerufen": "2026-09-18",
 "jahr": 2030, "herausgeber": "…"}
{"wert": 30, "einheit": "% Umsatz", "typ": "schaetzung", "begruendung": "Herleitung in 1–3 Sätzen", "abgerufen": "2026-09-18"}
```
- `berichtet` braucht `quelle` (URL), `schaetzung` braucht `begruendung`. Fehlt ein Wert: `"wert": null` plus `hinweis` – nie auffüllen.
- Schätzungen sind erlaubt, müssen aber als Schätzung markiert und begründet sein.

## Quellenqualität (absteigend)
1. Geschäftsberichte, Behörden, Statistikämter
2. Branchenverbände
3. Studien mit offengelegter Methodik
4. Pressemitteilungen von Marktforschern – nur mit `hinweis` („Pressemitteilung, Methodik nicht einsehbar“)

## Datei-Eigentum
- Jeder Agent schreibt **ausschließlich seine eigene Datei** (die im Titel seiner Aufgabe). Fremde Dateien nur lesen.
- Agenten liefern JSON nach Schema, keinen Fließtext.
- Vor dem Abschließen selbst prüfen: `python3 tools/validate.py <datei>`.

## Aufgaben und Türsteher
- Aufgabentitel: `[runs/<lauf>/<datei>.json] Titel`, z. B. `[runs/robotik-2026-09-18/firmen/NVDA.json] Deep Dive NVIDIA`.
- Aufgaben ohne eigene Datei beginnen mit `Koordination:`.
- Beim Erledigen prüft der Türsteher (Hook) die Datei. **Eine Ablehnung wird korrigiert, nicht diskutiert:** Fehler beheben, Aufgabe erneut als erledigt markieren.

## Team
| Name | Typ (`.claude/agents/`) | Datei |
|---|---|---|
| `markt` | markt | `markt-groesse.json` |
| `treiber` | treiber | `treiber.json` |
| `kette` | kette | `kette.json` |
| `firma-1` … `firma-4` | firma | `firmen/<TICKER>.json` |
| `red-team` | red-team | `redteam.json` |
| Lead | – | `lauf.json`, `shortlist.json`, `report.json` |

## Grenzen
- **Keine Anlageberatung:** keine Kauf- oder Verkaufsempfehlungen, keine Kursziele.
- Keine Namen, Logos oder Markenelemente realer Asset Manager.
