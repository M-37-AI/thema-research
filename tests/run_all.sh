#!/usr/bin/env bash
# Führt alle Offline-Tests aus: pytest für die Werkzeuge, dann die Hook-Tests.
# Aufruf: bash tests/run_all.sh   (venv aktiviert, pytest aus requirements-dev.txt)
set -u
cd "$(dirname "$0")/.."
PY="python3"; [ -x .venv/bin/python3 ] && PY=".venv/bin/python3"
echo "== Werkzeuge (pytest)"
"$PY" -m pytest tests/ -q || exit 1
echo; echo "== Türsteher-Hooks"
bash tests/test_gate.sh || exit 1
echo; echo "== Fixtures"
"$PY" tools/validate.py -q tests/fixtures/gut/*.json && echo "gültige Fixtures ✓"
"$PY" tools/validate.py -q tests/fixtures/kaputt/*.json >/dev/null 2>&1 && { echo "kaputte Fixtures wurden NICHT erkannt"; exit 1; } || echo "kaputte Fixtures werden erkannt ✓"
echo; echo "Alle Tests bestanden."
