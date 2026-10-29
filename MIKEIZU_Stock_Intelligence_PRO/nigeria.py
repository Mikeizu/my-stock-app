"""NGX research directory and retained, user-authorized daily market data.

.NGX is this app's namespace, not a Yahoo Finance exchange suffix. The directory
contains names, never fabricated quotes. Listing status must be checked with NGX.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
import json
import math
import os
from pathlib import Path
import re
import tempfile

import pandas as pd

NGX_SOURCE_URL = "https://ngxgroup.com/exchange/data/equities-price-list/"
DATA_DIR = Path(__file__).resolve().parent / "data" / "ngx"

_ROWS = [
    ("DANGCEM", "Dangote Cement Plc", "Industrial goods"),
    ("BUACEMENT", "BUA Cement Plc", "Industrial goods"),
    ("WAPCO", "Lafarge Africa Plc", "Industrial goods"),
    ("BUAFOODS", "BUA Foods Plc", "Consumer goods"),
    ("DANGSUGAR", "Dangote Sugar Refinery Plc", "Consumer goods"),
    ("NESTLE", "Nestle Nigeria Plc", "Consumer goods"),
    ("NB", "Nigerian Breweries Plc", "Consumer goods"),
    ("INTBREW", "International Breweries Plc", "Consumer goods"),
    ("UNILEVER", "Unilever Nigeria Plc", "Consumer goods"),
    ("CADBURY", "Cadbury Nigeria Plc", "Consumer goods"),
    ("GTCO", "Guaranty Trust Holding Company Plc", "Financial services"),
    ("ZENITHBANK", "Zenith Bank Plc", "Financial services"),
    ("ACCESSCORP", "Access Holdings Plc", "Financial services"),
    ("UBA", "United Bank for Africa Plc", "Financial services"),
    ("FIRSTHOLDCO", "First HoldCo Plc", "Financial services"),
    ("FIDELITYBK", "Fidelity Bank Plc", "Financial services"),
    ("FCMB", "FCMB Group Plc", "Financial services"),
    ("STANBIC", "Stanbic IBTC Holdings Plc", "Financial services"),
    ("UCAP", "United Capital Plc", "Financial services"),
    ("CUSTODIAN", "Custodian Investment Plc", "Financial services"),
    ("AIICO", "AIICO Insurance Plc", "Financial services"),
    ("NEM", "NEM Insurance Plc", "Financial services"),
    ("MANSARD", "AXA Mansard Insurance Plc", "Financial services"),
    ("MTNN", "MTN Nigeria Communications Plc", "Telecommunications"),
    ("AIRTELAFRI", "Airtel Africa Plc", "Telecommunications"),
    ("SEPLAT", "Seplat Energy Plc", "Energy"),
    ("OANDO", "Oando Plc", "Energy"),
    ("CONOIL", "Conoil Plc", "Energy"),
    ("TOTAL", "TotalEnergies Marketing Nigeria Plc", "Energy"),
    ("GEREGU", "Geregu Power Plc", "Utilities"),
    ("TRANSPOWER", "Transcorp Power Plc", "Utilities"),
    ("TRANSCORP", "Transnational Corporation Plc", "Conglomerates"),
    ("PRESCO", "Presco Plc", "Agriculture"),
    ("OKOMUOIL", "The Okomu Oil Palm Company Plc", "Agriculture"),
    ("NAHCO", "Nigerian Aviation Handling Company Plc", "Services"),
    ("SAHCO", "Skyway Aviation Handling Company Plc", "Services"),
]
NGX_COMPANIES = {symbol: {"name": name, "sector": sector, "source_url": NGX_SOURCE_URL}
                 for symbol, name, sector in _ROWS}


class NGXDataUnavailable(ValueError):
    """The company is known, but no authorized price history is installed."""


def normalize_ngx_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    if raw.endswith(".NGX"):
        raw = raw[:-4]
    if not re.fullmatch(r"[A-Z0-9]{1,18}", raw) or raw not in NGX_COMPANIES:
        raise ValueError("Choose a ticker in the Nigerian NGX directory; .NGX is an internal app identifier, not a Yahoo code.")
    return raw + ".NGX"


def ngx_profile(symbol: str) -> dict:
    symbol = normalize_ngx_symbol(symbol)
    row = NGX_COMPANIES[symbol[:-4]]
    return {"longName": row["name"], "sector": row["sector"], "currency": "NGN",
            "country": "Nigeria", "exchange": "NGX", "source_url": NGX_SOURCE_URL,
            "symbol": symbol, "directory_only": True}


def ngx_search(query: str, limit: int = 10) -> list[dict]:
    text = str(query or "").strip().casefold()
    if len(text) < 2:
        raise ValueError("Enter at least two characters of a company name or ticker.")
    if len(text) > 100:
        raise ValueError("Keep company searches under 100 characters.")
    text = text.removesuffix(".ngx")
    matches = [symbol for symbol, row in NGX_COMPANIES.items()
               if text in symbol.casefold() or text in row["name"].casefold() or text in row["sector"].casefold()]
    matches.sort(key=lambda s: (s.casefold() != text, not s.casefold().startswith(text), s))
    return [{"symbol": s + ".NGX", "name": NGX_COMPANIES[s]["name"], "exchange": "NGX",
             "country": "Nigeria"} for s in matches[:max(1, min(int(limit), 40))]]


_NUMERIC_FIELDS = {"profitMargins", "returnOnEquity", "debtToEquity", "revenueGrowth",
                   "earningsGrowth", "earningsQuarterlyGrowth", "trailingPE", "payoutRatio",
                   "beta", "marketCap", "targetMeanPrice", "numberOfAnalystOpinions"}
_TEXT_FIELDS = {"fundamentals_as_of", "fundamentals_source", "fundamentals_reference"}


def _safe_metadata(symbol, info):
    result = ngx_profile(symbol)
    result["directory_only"] = False
    info = info or {}
    if info.get("currency") and info["currency"] != "NGN":
        raise ValueError("NGX retained histories must use NGN. Convert source units before importing.")
    for key in _NUMERIC_FIELDS:
        if key in info and info[key] is not None:
            try:
                value = float(info[key])
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f"Invalid finite number for {key}") from None
            if not math.isfinite(value):
                raise ValueError(f"Invalid finite number for {key}")
            result[key] = value
    for key in _TEXT_FIELDS:
        if key in info and info[key] is not None:
            result[key] = str(info[key])[:300]
    if any(k in result for k in _NUMERIC_FIELDS):
        result["fundamentals_source"] = "User import"
    return result


def _paths(symbol, data_dir):
    symbol = normalize_ngx_symbol(symbol)
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    return symbol, root, root / (symbol[:-4] + ".csv"), root / (symbol[:-4] + ".fundamentals.json")


def _atomic_write(path: Path, content: str):
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def save_ng_market(symbol: str, prices: pd.DataFrame, info: dict | None = None, *, data_dir=None):
    """Retain only an explicitly imported history and whitelisted metadata locally."""
    from providers import csv_market
    symbol, root, csv_path, info_path = _paths(symbol, data_dir)
    metadata = _safe_metadata(symbol, info)
    frame = prices.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("NGX price data must have a dated index.")
    if "Close" not in frame:
        raise ValueError("NGX price data must include Close.")
    flags = info or {}
    columns = ["Close"]
    if "Adj Close" in frame and flags.get("price_adjusted", True):
        columns.append("Adj Close")
    if "Dividends" in frame and flags.get("dividends_supplied", True):
        columns.append("Dividends")
    # Reuse the import validation; do not keep synthetic raw-close adjustments.
    frame, imported, _ = csv_market(StringIO(frame[columns].to_csv(index_label="Date")), metadata["longName"])
    retained = frame[columns]
    metadata.update({"price_adjusted": imported["price_adjusted"],
                     "dividends_supplied": imported["dividends_supplied"],
                     "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    root.mkdir(parents=True, exist_ok=True)
    _atomic_write(csv_path, retained.to_csv(index_label="Date"))
    _atomic_write(info_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    return load_ng_market(symbol, data_dir=root)


def load_ng_market(symbol: str, *, data_dir=None):
    """Read authorized local NGX history; never fall back to an unrelated US quote."""
    from providers import csv_market
    symbol, root, csv_path, info_path = _paths(symbol, data_dir)
    if not csv_path.is_file():
        raise NGXDataUnavailable(
            f"{symbol[:-4]} is in the NGX directory, but no authorized price history is installed. "
            "Import a daily CSV and optionally dated fundamentals; news research remains available. "
            "No live Nigerian price feed is bundled.")
    stored = {}
    if info_path.is_file():
        if info_path.stat().st_size > 20000:
            raise ValueError("NGX metadata file is too large.")
        with info_path.open(encoding="utf-8") as handle:
            stored = json.load(handle)
        if not isinstance(stored, dict):
            raise ValueError("NGX metadata must be an object.")
    info = _safe_metadata(symbol, stored)
    with csv_path.open("rb") as handle:
        prices, imported, fetched = csv_market(handle, info["longName"])
    info.update({"price_adjusted": imported["price_adjusted"],
                 "dividends_supplied": imported["dividends_supplied"],
                 "source": "Retained user-authorized NGX CSV", "source_url": NGX_SOURCE_URL})
    return prices, info, fetched
