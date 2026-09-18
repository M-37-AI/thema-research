#!/usr/bin/env bash
# Testet die Türsteher-Hooks: schickt Beispiel-Hook-JSON an gate.py und gate_create.py
# und prüft die Exit-Codes. Läuft in einem temporären Projektordner (CLAUDE_PROJECT_DIR),
# damit runs/ im echten Projekt unberührt bleibt.
#
# Aufruf: bash tests/test_gate.sh
set -u

PROJEKT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PROJEKT/.venv/bin/python3"
[ -x "$PY" ] || PY="python3"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_PROJECT_DIR="$TMP"
LAUF="runs/test-2026-01-01"
mkdir -p "$TMP/$LAUF"
cp "$PROJEKT/tests/fixtures/gut/kette.json" "$TMP/$LAUF/kette.json"
cp "$PROJEKT/tests/fixtures/kaputt/markt-groesse--zu-wenige-schaetzungen.json" "$TMP/$LAUF/markt-groesse.json"

bestanden=0; fehlgeschlagen=0

pruefe() {  # pruefe <beschreibung> <skript> <erwarteter-exit> <json>
  local beschreibung="$1" skript="$2" erwartet="$3" json="$4" code stderr
  stderr="$(printf '%s' "$json" | "$PY" "$PROJEKT/tools/$skript" 2>&1 >/dev/null)"
  code=$?
  # Auffüllen nach Zeichen statt Bytes, damit Umlaute die Spalten nicht verschieben
  local fuell=$((34 - ${#beschreibung})); local luecke; luecke="$(printf '%*s' "$fuell" '')"
  if [ "$code" -eq "$erwartet" ]; then
    printf '  ✓ %s%s Exit %s\n' "$beschreibung" "$luecke" "$code"; bestanden=$((bestanden + 1))
  else
    printf '  ✗ %s%s Exit %s, erwartet %s\n' "$beschreibung" "$luecke" "$code" "$erwartet"
    printf '%s\n' "$stderr" | sed 's/^/      /'
    fehlgeschlagen=$((fehlgeschlagen + 1))
  fi
}

echo "TaskCompleted (gate.py):"
pruefe "gültige Datei"                gate.py 0 '{"hook_event_name":"TaskCompleted","task_subject":"['"$LAUF"'/kette.json] Wertschöpfungskette","teammate_name":"kette"}'
pruefe "kaputte Datei"                gate.py 2 '{"hook_event_name":"TaskCompleted","task_subject":"['"$LAUF"'/markt-groesse.json] Marktgröße","teammate_name":"markt"}'
pruefe "fehlende Datei"               gate.py 2 '{"hook_event_name":"TaskCompleted","task_subject":"['"$LAUF"'/treiber.json] Treiber","teammate_name":"treiber"}'
pruefe "kein Pfad"                    gate.py 0 '{"hook_event_name":"TaskCompleted","task_subject":"Koordination: Shortlist festlegen"}'
pruefe "Pfad nur in der Beschreibung" gate.py 0 '{"hook_event_name":"TaskCompleted","task_subject":"Kette","task_description":"Ergebnis: ['"$LAUF"'/kette.json]"}'
pruefe "Pfad mit .."                  gate.py 2 '{"hook_event_name":"TaskCompleted","task_subject":"[runs/../geheim.json] x"}'

echo "TaskCreated (gate_create.py):"
pruefe "Aufgabe mit Konvention"       gate_create.py 0 '{"hook_event_name":"TaskCreated","task_subject":"['"$LAUF"'/firmen/NVDA.json] Deep Dive NVIDIA"}'
pruefe "Koordinationsaufgabe"         gate_create.py 0 '{"hook_event_name":"TaskCreated","task_subject":"Koordination: Shortlist festlegen"}'
pruefe "Aufgabe ohne Konvention"      gate_create.py 2 '{"hook_event_name":"TaskCreated","task_subject":"Recherchiere den Markt"}'

echo "Protokoll:"
LOG="$TMP/$LAUF/gate-log.jsonl"
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" | tr -d ' ')" -eq 4 ]; then
  echo "  ✓ gate-log.jsonl enthält 4 Entscheidungen"; bestanden=$((bestanden + 1))
else
  echo "  ✗ gate-log.jsonl fehlt oder hat nicht 4 Einträge"; fehlgeschlagen=$((fehlgeschlagen + 1))
fi

echo
echo "$bestanden bestanden, $fehlgeschlagen fehlgeschlagen."
[ "$fehlgeschlagen" -eq 0 ]
