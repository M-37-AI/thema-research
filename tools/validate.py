#!/usr/bin/env python3
"""Prüft JSON-Dateien des Research-Teams gegen ihre Schemas.

Das Schema wird aus dem Dateinamen abgeleitet:
  markt-groesse.json, treiber.json, kette.json, markt.json, redteam.json,
  report.json, zahl.json  -> gleichnamiges Schema
  firmen/<TICKER>.json    -> Schema "firma"
Der Teil vor "--" zählt, z. B. "kette--falscher-enum.json" -> "kette".

Zusätzlich:
  - Jedes Objekt mit dem Schlüssel "wert" wird gegen das Zahl-Schema geprüft.
  - Im Report werden alle Verweise {ref:<datei>#<json-pointer>} aufgelöst
    (relativ zum Ordner der Report-Datei); ausgeschriebene Beträge ergeben
    eine Warnung.

Exit-Code: 0 = alle Dateien gültig (Warnungen erlaubt), 1 = mindestens ein Fehler.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

PROJEKT = Path(__file__).resolve().parent.parent
SCHEMA_ORDNER = PROJEKT / "schemas"
SCHEMA_NAMEN = ["zahl", "markt-groesse", "treiber", "kette", "markt", "firma", "redteam", "report"]

REF_MUSTER = re.compile(r"\{ref:([^#}\s]+)#([^}\s]*)\}")
# Beträge, die im Report-Text eigentlich als Verweis stehen sollten
BETRAG_MUSTER = re.compile(
    r"\d[\d.,]*\s*(?:Mrd|Mio|Bio|Tsd|%|Prozent|USD|EUR|CHF|JPY|\$|€)", re.IGNORECASE
)


# ---------------------------------------------------------------- Schemas

def _lade_registry() -> tuple[Registry, dict[str, dict]]:
    schemas: dict[str, dict] = {}
    registry = Registry()
    for name in SCHEMA_NAMEN:
        pfad = SCHEMA_ORDNER / f"{name}.schema.json"
        schema = json.loads(pfad.read_text(encoding="utf-8"))
        schemas[name] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry, schemas


_REGISTRY, _SCHEMAS = _lade_registry()


def validator_fuer(schema_name: str) -> Draft202012Validator:
    return Draft202012Validator(_SCHEMAS[schema_name], registry=_REGISTRY)


def schema_fuer_datei(pfad: Path) -> str | None:
    """Leitet den Schema-Namen aus Dateiname bzw. Ordner ab."""
    if pfad.parent.name == "firmen":
        return "firma"
    stamm = pfad.stem.split("--")[0]
    if stamm.startswith("firma"):
        return "firma"
    return stamm if stamm in SCHEMA_NAMEN else None


# ---------------------------------------------------------------- Fehlertexte

def json_pfad(teile) -> str:
    """['segmente', 2, 'marktgroesse'] -> 'segmente[2].marktgroesse'"""
    text = ""
    for teil in teile:
        if isinstance(teil, int):
            text += f"[{teil}]"
        else:
            text += f".{teil}" if text else str(teil)
    return text or "(Wurzel)"


def _typname(wert) -> str:
    return {
        dict: "Objekt", list: "Liste", str: "Text", bool: "Wahrheitswert",
        int: "Zahl", float: "Zahl", type(None): "null",
    }.get(type(wert), type(wert).__name__)


_TYP_DEUTSCH = {
    "object": "Objekt", "array": "Liste", "string": "Text", "number": "Zahl",
    "integer": "ganze Zahl", "boolean": "Wahrheitswert", "null": "null",
}


def fehlertext(fehler) -> str:
    """Übersetzt einen jsonschema-Fehler in eine verständliche deutsche Meldung."""
    art = fehler.validator
    wert = fehler.instance
    regel = fehler.validator_value

    if art == "required":
        feld = re.search(r"'([^']+)' is a required property", fehler.message)
        feld = feld.group(1) if feld else "Pflichtfeld"
        text = f"{feld} fehlt"
        if isinstance(wert, dict) and "typ" in wert and feld in ("quelle", "begruendung"):
            text += f" (typ={wert['typ']})"
        return text
    if isinstance(fehler.schema, dict) and "fehlertext" in fehler.schema:
        return f"{wert!r} {fehler.schema['fehlertext']}"
    if art == "enum":
        return f"ungültiger Wert {wert!r}, erlaubt: {' | '.join(map(str, regel))}"
    if art == "const":
        return f"muss {regel!r} sein, ist {wert!r}"
    if art == "type":
        erwartet = regel if isinstance(regel, list) else [regel]
        return f"falscher Typ ({_typname(wert)}), erwartet: {' oder '.join(_TYP_DEUTSCH.get(t, t) for t in erwartet)}"
    if art == "minItems":
        return f"zu wenige Einträge ({len(wert)}), mindestens {regel}"
    if art == "maxItems":
        return f"zu viele Einträge ({len(wert)}), höchstens {regel}"
    if art == "minLength":
        return "leer" if not wert else f"zu kurz ({len(wert)} Zeichen, mindestens {regel})"
    if art == "maxLength":
        return f"zu lang ({len(wert)} Zeichen, höchstens {regel})"
    if art == "additionalProperties":
        erlaubt = set(fehler.schema.get("properties", {}))
        extra = sorted(k for k in wert if k not in erlaubt)
        return f"unbekannte(s) Feld(er): {', '.join(extra)}"
    if art == "pattern":
        return f"{wert!r} hat ein ungültiges Format"
    return fehler.message


def _schema_fehler(daten, schema_name: str, praefix=()) -> list[str]:
    ergebnisse = []
    for fehler in validator_fuer(schema_name).iter_errors(daten):
        # Bei allOf/if-then liefert jsonschema die Einzelfehler als Kontext
        einzelne = [fehler] if not fehler.context else list(fehler.context)
        for f in einzelne:
            pfad = json_pfad(list(praefix) + list(f.absolute_path))
            ergebnisse.append(f"{pfad}: {fehlertext(f)}")
    return ergebnisse


def _alle_zahl_objekte(daten, pfad=()):
    """Findet rekursiv jedes Objekt mit dem Schlüssel 'wert'."""
    if isinstance(daten, dict):
        if "wert" in daten:
            yield pfad, daten
        for schluessel, inhalt in daten.items():
            yield from _alle_zahl_objekte(inhalt, pfad + (schluessel,))
    elif isinstance(daten, list):
        for i, inhalt in enumerate(daten):
            yield from _alle_zahl_objekte(inhalt, pfad + (i,))


# ---------------------------------------------------------------- Verweise im Report

def json_pointer_aufloesen(daten, pointer: str):
    """Löst einen JSON-Pointer (RFC 6901) auf; wirft KeyError bei Fehlschlag."""
    if pointer in ("", "/"):
        return daten
    if not pointer.startswith("/"):
        raise KeyError("Pointer muss mit / beginnen")
    aktuell = daten
    for roh in pointer[1:].split("/"):
        teil = roh.replace("~1", "/").replace("~0", "~")
        if isinstance(aktuell, list):
            if not teil.isdigit() or int(teil) >= len(aktuell):
                raise KeyError(f"Index {teil} existiert nicht")
            aktuell = aktuell[int(teil)]
        elif isinstance(aktuell, dict):
            if teil not in aktuell:
                raise KeyError(f"Schlüssel '{teil}' existiert nicht")
            aktuell = aktuell[teil]
        else:
            raise KeyError(f"'{teil}' zeigt in einen Einzelwert")
    return aktuell


def _alle_texte(daten, pfad=()):
    if isinstance(daten, str):
        yield pfad, daten
    elif isinstance(daten, dict):
        for schluessel, inhalt in daten.items():
            yield from _alle_texte(inhalt, pfad + (schluessel,))
    elif isinstance(daten, list):
        for i, inhalt in enumerate(daten):
            yield from _alle_texte(inhalt, pfad + (i,))


def verweis_aufloesen(lauf_ordner: Path, datei: str, pointer: str, _cache: dict | None = None):
    """Gibt das Zahl-Objekt hinter einem Verweis zurück oder wirft ValueError mit Grund."""
    ziel = (lauf_ordner / datei).resolve()
    if _cache is not None and ziel in _cache:
        inhalt = _cache[ziel]
    else:
        if not ziel.is_file():
            raise ValueError("Datei fehlt")
        try:
            inhalt = json.loads(ziel.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise ValueError("Zieldatei ist kein gültiges JSON")
        if _cache is not None:
            _cache[ziel] = inhalt
    try:
        objekt = json_pointer_aufloesen(inhalt, pointer)
    except KeyError as e:
        raise ValueError(f"Pfad nicht gefunden: {e.args[0]}")
    if not (isinstance(objekt, dict) and "wert" in objekt):
        raise ValueError("Ziel ist kein Zahl-Objekt")
    if list(validator_fuer("zahl").iter_errors(objekt)):
        raise ValueError("Ziel ist kein gültiges Zahl-Objekt")
    return objekt


def _report_pruefen(daten, lauf_ordner: Path) -> tuple[list[str], list[str]]:
    fehler, warnungen, cache = [], [], {}
    for pfad, text in _alle_texte(daten):
        for treffer in REF_MUSTER.finditer(text):
            datei, pointer = treffer.group(1), treffer.group(2)
            try:
                verweis_aufloesen(lauf_ordner, datei, pointer, cache)
            except ValueError as grund:
                fehler.append(f"{json_pfad(pfad)}: Verweis {datei}#{pointer} nicht auflösbar ({grund})")
        ohne_verweise = REF_MUSTER.sub("", text)
        for betrag in BETRAG_MUSTER.finditer(ohne_verweise):
            warnungen.append(
                f"{json_pfad(pfad)}: ausgeschriebene Zahl „{betrag.group(0).strip()}“ "
                "– bitte als {ref:<datei>#<pfad>} angeben"
            )
    return fehler, warnungen


# ---------------------------------------------------------------- Einstieg

def validiere_datei(pfad: Path, schema_name: str | None = None) -> tuple[list[str], list[str]]:
    """Prüft eine Datei. Rückgabe: (fehler, warnungen). Wird auch von gate.py genutzt."""
    pfad = Path(pfad)
    if not pfad.is_file():
        return [f"Datei nicht gefunden: {pfad}"], []
    schema_name = schema_name or schema_fuer_datei(pfad)
    if schema_name is None:
        return [f"Kein Schema für '{pfad.name}' bekannt (erwartet: {', '.join(SCHEMA_NAMEN)} oder firmen/<TICKER>.json)"], []
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"Kein gültiges JSON (Zeile {e.lineno}, Spalte {e.colno}): {e.msg}"], []

    fehler = _schema_fehler(daten, schema_name)
    if schema_name != "zahl":
        for zpfad, objekt in _alle_zahl_objekte(daten):
            fehler += _schema_fehler(objekt, "zahl", zpfad)
    warnungen: list[str] = []
    if schema_name == "report":
        ref_fehler, warnungen = _report_pruefen(daten, pfad.parent)
        fehler += ref_fehler
    # Doppelte Meldungen (Schema-$ref + rekursive Zahl-Prüfung) entfernen
    return list(dict.fromkeys(fehler)), list(dict.fromkeys(warnungen))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Prüft Research-Dateien gegen ihre JSON-Schemas (Schema aus dem Dateinamen).",
        epilog="Beispiel: python3 tools/validate.py runs/robotik-2026-09-18/*.json",
    )
    parser.add_argument("dateien", nargs="+", type=Path, help="zu prüfende JSON-Dateien")
    parser.add_argument("--schema", choices=SCHEMA_NAMEN, help="Schema erzwingen statt aus dem Namen ableiten")
    parser.add_argument("-q", "--leise", action="store_true", help="nur Fehler ausgeben")
    args = parser.parse_args(argv)

    gesamt_fehler = 0
    for datei in args.dateien:
        fehler, warnungen = validiere_datei(datei, args.schema)
        if fehler:
            gesamt_fehler += len(fehler)
            print(f"✗ {datei}  ({len(fehler)} Fehler)")
            for f in fehler:
                print(f"    {f}")
        elif not args.leise:
            print(f"✓ {datei}")
        if not args.leise:
            for w in warnungen:
                print(f"    ! {w}")

    if len(args.dateien) > 1 and not args.leise:
        print(f"\n{len(args.dateien)} Dateien geprüft, {gesamt_fehler} Fehler.")
    return 1 if gesamt_fehler else 0


if __name__ == "__main__":
    sys.exit(main())
