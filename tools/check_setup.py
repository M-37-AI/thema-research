#!/usr/bin/env python3
"""Prüft, ob alles für einen Lauf bereit ist – bevor man /thema startet.

Geprüft werden: Python-Version, venv, Pakete, Claude Code (Version, Agent Teams),
tmux, Projekt-Settings, Yahoo-Finance-Erreichbarkeit (optional mit --online).

Exit-Code: 0 = alles bereit, 1 = mindestens ein Problem.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent
MIN_CLAUDE = (2, 1, 178)   # ab hier startet ein benannter Agent als Teammate ohne TeamCreate
MIN_PYTHON = (3, 11)

probleme: list[str] = []


def zeile(ok: bool | None, text: str, hinweis: str = "") -> None:
    symbol = {True: "✓", False: "✗", None: "·"}[ok]
    print(f"  {symbol} {text}" + (f"\n      → {hinweis}" if hinweis else ""))
    if ok is False:
        probleme.append(text)


def version_tuple(text: str) -> tuple[int, ...]:
    treffer = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(x) for x in treffer.groups()) if treffer else (0,)


def pruefe_python() -> None:
    print("Python")
    v = sys.version_info
    zeile(v[:2] >= MIN_PYTHON, f"Python {v.major}.{v.minor}.{v.micro}",
          "" if v[:2] >= MIN_PYTHON else f"mindestens {'.'.join(map(str, MIN_PYTHON))} nötig – das macOS-eigene python3 ist zu alt: brew install uv && uv venv --python 3.12 .venv")
    im_venv = sys.prefix != sys.base_prefix
    venv_pfad = PROJEKT / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin") / "python3"
    zeile(im_venv, "venv aktiv" if im_venv else "kein venv aktiv", "" if im_venv else "source .venv/bin/activate")
    zeile(venv_pfad.exists() or (venv_pfad.with_name("python.exe")).exists(), f"{venv_pfad.relative_to(PROJEKT)} vorhanden (Hooks brauchen genau diesen Pfad)",
          "" if venv_pfad.exists() else "python3 -m venv .venv  oder  uv venv --python 3.12 .venv")
    for paket in ("yfinance", "jsonschema", "jinja2", "pandas"):
        try:
            zeile(True, f"{paket} {importlib.metadata.version(paket)}")
        except importlib.metadata.PackageNotFoundError:
            zeile(False, f"{paket} fehlt", "uv pip install -r requirements.txt  (uv-venv)  bzw.  pip install -r requirements.txt")
    if platform.system() == "Windows":
        zeile(None, "Windows: Hooks in .claude/settings.json zeigen auf .venv/bin/python3 – Pfad auf .venv\\Scripts\\python.exe anpassen")


def pruefe_claude() -> None:
    print("Claude Code")
    pfad = shutil.which("claude")
    if not pfad:
        zeile(False, "claude nicht gefunden", "https://code.claude.com/docs installieren")
        return
    try:
        ausgabe = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:  # noqa: BLE001
        zeile(False, f"claude --version fehlgeschlagen ({e})")
        return
    v = version_tuple(ausgabe)
    zeile(v >= MIN_CLAUDE, f"Claude Code {ausgabe}", "" if v >= MIN_CLAUDE else f"mindestens {'.'.join(map(str, MIN_CLAUDE))} – claude update")
    settings = PROJEKT / ".claude" / "settings.json"
    try:
        env = json.loads(settings.read_text(encoding="utf-8")).get("env", {})
    except Exception:  # noqa: BLE001
        env = {}
    zeile(env.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") == "1", "Agent Teams in .claude/settings.json aktiviert")
    zeile(env.get("CLAUDE_CODE_ENABLE_TODO_TOOLS") == "1", "Task-Tools in .claude/settings.json aktiviert (sonst feuern die Türsteher-Hooks nie)")
    for hook in ("TaskCreated", "TaskCompleted"):
        try:
            hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {})
        except Exception:  # noqa: BLE001
            hooks = {}
        zeile(hook in hooks, f"Hook {hook} registriert")
    rollen = sorted(p.stem for p in (PROJEKT / ".claude" / "agents").glob("*.md"))
    erwartet = ["firma", "kette", "lektor", "markt", "red-team", "treiber"]
    zeile(rollen == erwartet, f"Rollen: {', '.join(rollen)}", "" if rollen == erwartet else f"erwartet: {', '.join(erwartet)}")
    zeile((PROJEKT / ".claude/skills/thema/SKILL.md").exists(), "Skill /thema vorhanden")


def pruefe_terminal() -> None:
    print("Anzeige")
    tmux = shutil.which("tmux")
    zeile(bool(tmux), "tmux installiert" if tmux else "tmux fehlt (Split-Pane-Ansicht)", "" if tmux else "brew install tmux – oder ohne tmux starten (Teammates erscheinen dann im Agenten-Panel)")
    if os.environ.get("TMUX"):
        zeile(None, "Du bist bereits in einer tmux-Session – claude --teammate-mode tmux öffnet die Teammates hier als Panes")


def pruefe_online() -> None:
    print("Datenquelle (online)")
    try:
        sys.path.insert(0, str(PROJEKT / "tools"))
        import kennzahlen  # noqa: PLC0415
        k = kennzahlen.hole_kennzahlen("NVDA", neu=True)
        zeile(k["kennzahlen"]["marktkapitalisierung"]["wert"] is not None, f"Yahoo Finance erreichbar (NVDA: {k['name']})")
    except Exception as e:  # noqa: BLE001
        zeile(False, f"Yahoo Finance nicht erreichbar: {e}", "Netz prüfen; yfinance ggf. aktualisieren")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prüft die Voraussetzungen für einen Lauf mit /thema.")
    parser.add_argument("--online", action="store_true", help="zusätzlich einen Test-Abruf bei Yahoo Finance machen")
    args = parser.parse_args(argv)
    print(f"thema-research · Setup-Check ({platform.system()})\n")
    pruefe_python()
    pruefe_claude()
    pruefe_terminal()
    if args.online:
        pruefe_online()
    print()
    if probleme:
        print(f"✗ {len(probleme)} Problem(e) – siehe oben.")
        return 1
    print("✓ Alles bereit. Starten mit:  claude --teammate-mode tmux   und dann  /thema <trend>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
