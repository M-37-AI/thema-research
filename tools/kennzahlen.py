#!/usr/bin/env python3
"""Holt Finanzkennzahlen per yfinance und speichert sie als Zahl-Objekte.

Ausgabe:  data/kennzahlen/<TICKER>.json
Rohdaten: data/cache/<TICKER>.json (und data/cache/fx/<PAAR>.json)

Jeder Wert ist ein Zahl-Objekt (typ "berichtet", Quelle Yahoo Finance).
Fehlende Werte bleiben null und bekommen einen Hinweis – es wird nichts aufgefüllt.

Achtung Währungen: Kurs und Marktkapitalisierung stehen in der Handelswährung
("currency"), Umsatz in der Berichtswährung ("financialCurrency"). Beispiel ABBN.SW:
Handel in CHF, Bericht in USD. Pence-Notierungen (GBp) werden auf GBP normalisiert;
Yahoo liefert die Marktkapitalisierung dort bereits in GBP.

Exit-Code: 0 = alle Ticker ok, 1 = mindestens ein Ticker fehlgeschlagen, 2 = Aufruffehler.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent
CACHE = PROJEKT / "data" / "cache"
AUSGABE = PROJEKT / "data" / "kennzahlen"

# Welche Felder aus yfinance .info gebraucht werden (Rohdaten im Cache)
ROH_FELDER = [
    "longName", "shortName", "currency", "financialCurrency", "quoteType", "exchange",
    "sector", "industry", "country", "marketCap", "totalRevenue", "revenueGrowth",
    "grossMargins", "operatingMargins", "enterpriseToRevenue", "trailingPE",
]
# Untereinheiten, in denen Yahoo manche Börsen notiert
UNTERWAEHRUNG = {"GBp": "GBP", "GBX": "GBP", "ZAc": "ZAR", "ILA": "ILS"}


class KennzahlenFehler(Exception):
    """Ticker unbekannt, keine Daten oder Cache fehlt im Offline-Modus."""


def heute() -> str:
    return dt.date.today().isoformat()


def quelle(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}"


def _cache_datei(name: str) -> Path:
    return CACHE / f"{name.replace('/', '_')}.json"


def _lies_cache(pfad: Path) -> dict | None:
    if pfad.is_file():
        return json.loads(pfad.read_text(encoding="utf-8"))
    return None


def _schreib_json(pfad: Path, daten: dict) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _yfinance():
    import yfinance as yf
    # yfinance loggt 404-Fehler selbst auf stderr – wir melden sie verständlicher
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return yf


# ---------------------------------------------------------------- Rohdaten

def hole_rohdaten(ticker: str, offline: bool = False, neu: bool = False) -> dict:
    """Liefert {abgerufen, info} – aus dem Cache (offline oder von heute) oder live."""
    pfad = _cache_datei(ticker)
    cache = _lies_cache(pfad)
    if offline:
        if cache is None:
            raise KennzahlenFehler(f"{ticker}: kein Cache vorhanden ({pfad.relative_to(PROJEKT)}) – erst ohne --offline abrufen")
        return cache
    if cache and cache.get("abgerufen") == heute() and not neu:
        return cache

    yf = _yfinance()
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:  # Netzwerk, Rate-Limit, ...
        raise KennzahlenFehler(f"{ticker}: Abruf fehlgeschlagen ({type(e).__name__}: {e})")
    if not info.get("quoteType") or info.get("marketCap") is None and info.get("totalRevenue") is None:
        raise KennzahlenFehler(f"{ticker}: unbekannter Ticker oder keine Daten bei Yahoo Finance (Börsensuffix prüfen, z. B. .DE, .SW, .T)")
    roh = {"ticker": ticker, "abgerufen": heute(), "info": {k: info.get(k) for k in ROH_FELDER}}
    _schreib_json(pfad, roh)
    return roh


def hole_fx(waehrung: str, offline: bool = False, neu: bool = False) -> dict:
    """Kurs 1 <waehrung> = x USD, als {kurs, datum, abgerufen}."""
    if waehrung == "USD":
        return {"kurs": 1.0, "datum": heute(), "abgerufen": heute()}
    paar = f"{waehrung}USD=X"
    pfad = CACHE / "fx" / f"{paar}.json"
    cache = _lies_cache(pfad)
    if offline:
        if cache is None:
            raise KennzahlenFehler(f"Wechselkurs {paar}: kein Cache vorhanden")
        return cache
    if cache and cache.get("abgerufen") == heute() and not neu:
        return cache
    yf = _yfinance()
    try:
        verlauf = yf.Ticker(paar).history(period="5d")
    except Exception as e:
        raise KennzahlenFehler(f"Wechselkurs {paar}: Abruf fehlgeschlagen ({e})")
    if verlauf.empty:
        raise KennzahlenFehler(f"Wechselkurs {paar}: keine Daten")
    fx = {"paar": paar, "kurs": float(verlauf["Close"].iloc[-1]),
          "datum": verlauf.index[-1].date().isoformat(), "abgerufen": heute()}
    _schreib_json(pfad, fx)
    return fx


# ---------------------------------------------------------------- Zahl-Objekte

def _zahl(wert, einheit: str, ticker: str, abgerufen: str, hinweis_wenn_leer: str, runden: int = 2) -> dict:
    objekt = {"wert": None if wert is None else round(float(wert), runden), "einheit": einheit,
              "typ": "berichtet", "quelle": quelle(ticker), "abgerufen": abgerufen,
              "herausgeber": "Yahoo Finance (via yfinance)"}
    if wert is None:
        objekt["hinweis"] = hinweis_wenn_leer
    return objekt


def _mal(wert, faktor):
    return None if wert is None else wert * faktor


def berechne(ticker: str, roh: dict, fx_handel: dict | None, fx_bericht: dict | None) -> dict:
    """Macht aus Rohdaten die Kennzahlen-Datei. fx_* = None, wenn der Kurs fehlt."""
    info, ab = roh["info"], roh["abgerufen"]
    handel = UNTERWAEHRUNG.get(info.get("currency"), info.get("currency")) or "?"
    bericht = UNTERWAEHRUNG.get(info.get("financialCurrency"), info.get("financialCurrency")) or handel
    fehlt = "von Yahoo Finance nicht geliefert"

    def fx_zahl(fx, waehrung):
        if fx is None:
            return _zahl(None, f"USD je {waehrung}", ticker, ab, "Wechselkurs nicht abrufbar", 6)
        z = _zahl(fx["kurs"], f"USD je {waehrung}", f"{waehrung}USD=X", fx["abgerufen"], "", 6)
        z["jahr"] = int(fx["datum"][:4])
        z["hinweis"] = f"Schlusskurs vom {fx['datum']}"
        return z

    def in_usd(wert, fx, was):
        if wert is None:
            return _zahl(None, "Mrd USD", ticker, ab, f"{was} fehlt")
        if fx is None:
            return _zahl(None, "Mrd USD", ticker, ab, "Wechselkurs nicht abrufbar")
        z = _zahl(wert * fx["kurs"] / 1e9, "Mrd USD", ticker, ab, "", 3)
        z["hinweis"] = f"umgerechnet mit {fx['kurs']:.6g} USD je Einheit (Kurs vom {fx['datum']})" if fx["kurs"] != 1.0 else "bereits in USD"
        return z

    pe = info.get("trailingPE")
    kgv = _zahl(pe, "x", ticker, ab, "nicht verfügbar (z. B. Verlust in den letzten 12 Monaten)")

    # Plausibilität EV/Umsatz: Yahoo liefert gelegentlich Unsinn (negativ, oder Marktkapitalisierung
    # und Umsatz in verschiedenen Währungen vermischt). Vergleich mit Marktkapitalisierung/Umsatz,
    # beides in USD. Unplausible Werte werden null – ein falscher Wert ist schlimmer als ein fehlender.
    ev_u = info.get("enterpriseToRevenue")
    ev_hinweis = None
    mk, um = info.get("marketCap"), info.get("totalRevenue")
    if ev_u is not None and mk and um and fx_handel and fx_bericht:
        kurs_umsatz = (mk * fx_handel["kurs"]) / (um * fx_bericht["kurs"])
        if ev_u <= 0:
            ev_hinweis = f"unplausibel: Yahoo meldet {ev_u:.2f}, Marktkapitalisierung/Umsatz ergibt {kurs_umsatz:.1f} – Wert verworfen"
        elif ev_u > kurs_umsatz * 3 or ev_u < kurs_umsatz / 3:
            ev_hinweis = (f"unplausibel: Yahoo meldet {ev_u:.2f}, Marktkapitalisierung/Umsatz ergibt {kurs_umsatz:.1f} "
                          "(Abweichung über Faktor 3) – Wert verworfen")
    ev_zahl = _zahl(None if ev_hinweis else ev_u, "x", ticker, ab, ev_hinweis or fehlt, 2)

    kennzahlen = {
        "marktkapitalisierung": _zahl(_mal(info.get("marketCap"), 1e-9), f"Mrd {handel}", ticker, ab, fehlt, 3),
        "umsatz_ttm": _zahl(_mal(info.get("totalRevenue"), 1e-9), f"Mrd {bericht}", ticker, ab, fehlt, 3),
        "umsatzwachstum_yoy": _zahl(_mal(info.get("revenueGrowth"), 100), "%", ticker, ab, fehlt, 1),
        "bruttomarge": _zahl(_mal(info.get("grossMargins"), 100), "%", ticker, ab, fehlt, 1),
        "operative_marge": _zahl(_mal(info.get("operatingMargins"), 100), "%", ticker, ab, fehlt, 1),
        "ev_umsatz": ev_zahl,
        "kgv": kgv,
    }
    hinweise = [f"{name}: {z['hinweis']}" for name, z in kennzahlen.items() if z["wert"] is None]
    if handel != bericht:
        hinweise.append(f"Handelswährung {handel}, Berichtswährung {bericht} – Umsatz und Marktkapitalisierung nicht direkt vergleichbar, USD-Werte verwenden")

    fx = {handel: fx_zahl(fx_handel, handel)}
    if bericht != handel:
        fx[bericht] = fx_zahl(fx_bericht, bericht)

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "waehrung": handel,
        "berichtswaehrung": bericht,
        "branche": info.get("industry"),
        "land": info.get("country"),
        "abgerufen": ab,
        "kennzahlen": kennzahlen,
        "umsatz_ttm_usd": in_usd(info.get("totalRevenue"), fx_bericht, "Umsatz"),
        "marktkapitalisierung_usd": in_usd(info.get("marketCap"), fx_handel, "Marktkapitalisierung"),
        "wechselkurse": fx,
        "hinweise": hinweise,
    }


def hole_kennzahlen(ticker: str, offline: bool = False, neu: bool = False) -> dict:
    """Öffentliche Funktion für andere Tools (z. B. screen.py): abrufen, berechnen, speichern."""
    ticker = ticker.strip().upper()
    roh = hole_rohdaten(ticker, offline, neu)
    info = roh["info"]
    handel = UNTERWAEHRUNG.get(info.get("currency"), info.get("currency"))
    bericht = UNTERWAEHRUNG.get(info.get("financialCurrency"), info.get("financialCurrency")) or handel

    def fx_oder_none(w):
        if not w:
            return None
        try:
            return hole_fx(w, offline, neu)
        except KennzahlenFehler:
            return None

    fx_handel = fx_oder_none(handel)
    fx_bericht = fx_handel if bericht == handel else fx_oder_none(bericht)
    ergebnis = berechne(ticker, roh, fx_handel, fx_bericht)
    _schreib_json(AUSGABE / f"{ticker}.json", ergebnis)
    return ergebnis


# ---------------------------------------------------------------- Terminal

def _fmt(z: dict, stellen: int = 1) -> str:
    if z["wert"] is None:
        return "–"
    return f"{z['wert']:,.{stellen}f}".replace(",", " ")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Holt Kennzahlen per yfinance und speichert sie nach data/kennzahlen/<TICKER>.json.",
        epilog="Beispiel: python3 tools/kennzahlen.py NVDA ABBN.SW 6954.T",
    )
    parser.add_argument("ticker", nargs="+", help="yfinance-Ticker inkl. Börsensuffix (z. B. ABBN.SW, 6954.T)")
    parser.add_argument("--offline", action="store_true", help="nur den Cache unter data/cache/ lesen")
    parser.add_argument("--neu", action="store_true", help="Cache von heute ignorieren und neu abrufen")
    args = parser.parse_args(argv)
    if args.offline and args.neu:
        parser.error("--offline und --neu schließen sich aus")

    sys.stdout.reconfigure(line_buffering=True)  # Reihenfolge stdout/stderr im Terminal
    fehlgeschlagen = 0
    print(f"{'Ticker':<10} {'Name':<28} {'MKap Mrd USD':>12} {'Umsatz Mrd USD':>14} {'Wachst.%':>8} {'Op.M.%':>7} {'EV/U':>6}")
    for t in args.ticker:
        try:
            k = hole_kennzahlen(t, args.offline, args.neu)
        except KennzahlenFehler as e:
            fehlgeschlagen += 1
            print(f"✗ {e}", file=sys.stderr)
            continue
        kz = k["kennzahlen"]
        print(f"{k['ticker']:<10} {k['name'][:28]:<28} {_fmt(k['marktkapitalisierung_usd']):>12} "
              f"{_fmt(k['umsatz_ttm_usd']):>14} {_fmt(kz['umsatzwachstum_yoy']):>8} "
              f"{_fmt(kz['operative_marge']):>7} {_fmt(kz['ev_umsatz']):>6}")
        for h in k["hinweise"]:
            print(f"{'':<10} ! {h}")
    if fehlgeschlagen:
        print(f"\n{fehlgeschlagen} von {len(args.ticker)} Tickern fehlgeschlagen.", file=sys.stderr)
    return 1 if fehlgeschlagen else 0


if __name__ == "__main__":
    sys.exit(main())
