---
name: report-stil
description: PFLICHT bei JEDEM Schreiben oder Überarbeiten von Report-Texten – report.json, Kernaussage, These, Abschnitte, Antworten auf Red-Team-Einwände, Beobachtungspunkte. Legt den institutionellen Research-Ton fest und die einzig erlaubte Schreibweise für Zahlen ({ref:…}). Immer laden, bevor auch nur ein Satz Report-Text entsteht – auch für kleine Korrekturen nach einer Türsteher-Ablehnung.
---

# Report-Stil

## Ton
- **Nüchtern, institutionell, „Wir“-Perspektive** des Research-Teams: „Wir sehen …“, „Wir halten … für wahrscheinlich“.
- Keine Superlative, keine Ausrufezeichen, keine Hype-Wörter („Revolution“, „Gamechanger“, „explodiert“).
- Unsicherheit klar benennen: „Die Datenlage ist dünn“, „Das ist eine Schätzung“.
- Kurze Absätze. Ein Gedanke pro Satz.

## Zahlen – nur als Verweis
Jede Zahl im Text ist ein Verweis auf ihr Zahl-Objekt. **Ausgeschriebene Beträge sind verboten** (validate.py warnt; der Renderer setzt Wert, „~“ für Schätzungen und Fußnote automatisch ein).

```
{ref:<datei>#<json-pointer>}
```
Der Pfad ist relativ zum Lauf-Ordner, der Pointer beginnt mit `/`, Listen werden ab 0 gezählt. Häufige Ziele:

| Was | Verweis |
|---|---|
| Marktschätzung Nr. 1 | `{ref:markt.json#/schaetzungen/0/marktgroesse}` |
| deren CAGR | `{ref:markt.json#/schaetzungen/0/cagr}` |
| Segmentgröße | `{ref:markt.json#/segmente/2/marktgroesse}` |
| Zahlen-Beleg eines Treibers (nur wenn Zahl-Objekt) | `{ref:markt.json#/treiber/1/belege/1}` |
| Themen-Exposure einer Firma | `{ref:firmen/NVDA.json#/themen_exposure}` |
| Kennzahl einer Firma | `{ref:../../data/kennzahlen/NVDA.json#/kennzahlen/operative_marge}` |
| Umsatz in USD | `{ref:../../data/kennzahlen/NVDA.json#/umsatz_ttm_usd}` |
| Bottom-up-Summe / Abdeckung | `{ref:bottom_up.json#/summe_themenumsatz}`, `{ref:bottom_up.json#/abdeckung_bei_oberer_schaetzung}` |

Jahreszahlen („bis 2030“) und Aufzählungen („drei Segmente“) sind keine Beträge und bleiben Text.

## Aufbau
- **`titel`:** eine Aussage, kein Schlagwort. „Robotik: Die Marge wandert zu den Komponenten“ statt „Robotik-Report“.
- **`kernaussage`:** höchstens **2 Sätze**. Was ist die Einsicht, und wie sicher sind wir?
- **`these`:** 1–2 Absätze, endet mit **„Was uns widerlegen würde: …“** – ein beobachtbares Ereignis.
- **`abschnitte`:**
  - `markt` – **Spannen statt Punktschätzungen:** „zwischen {ref:…} und {ref:…}“, Unterschiede in der Abgrenzung erklären. Nie mitteln.
  - `treiber_und_huerden` – die zwei, drei wichtigsten je Seite, mit Mechanismus.
  - `wertschoepfung` – wo sitzt die Marge, wo der Wettbewerb?
  - `unternehmen` – Rollen (Kernprofiteur/Zulieferer/Mitläufer), Exposure, was die Auswahl zeigt. Zu jeder Firmen-These ein „Was uns widerlegen würde“.
  - `risiken` – die stärksten Einwände des Red Teams in eigenen Worten.
- **`antworten_auf_einwaende`:** zu **jedem `hoch`-Einwand** aus `redteam.json`: `einwand_ref` (z. B. `E3`), `antwort` (sachlich, ohne Abwehrhaltung), `konsequenz` (was ändert sich an These oder Einordnung – „keine“ nur mit Begründung).
- **`beobachtungspunkte`:** **3–5** konkrete, beobachtbare Indikatoren (Kennzahl, Ereignis, Datum), die wir verfolgen.

## Verboten
- Kauf- oder Verkaufsempfehlungen, Kursziele, „Übergewichten“, „attraktiv bewertet“ als Handlungsaufforderung.
- Namen, Logos oder Markenelemente realer Asset Manager.
- Zahlen ohne Verweis, Punktschätzungen, wo eine Spanne existiert.
