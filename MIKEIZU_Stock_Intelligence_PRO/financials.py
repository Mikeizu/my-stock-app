"""Dated, user-supplied issuer fundamentals; never a replacement for source checks.

CSV ratios are decimals (0.20 = 20%); debt/equity is percentage points
(80 = 80%). Prices and financial statements retain their declared currency.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import math
from urllib.parse import urlsplit

import pandas as pd

from engine import get_metrics
from markets import MARKETS, resolve_symbols


FIELDS = {
    "profit_margin": "profitMargins", "roe": "returnOnEquity",
    "debt_eq": "debtToEquity", "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth", "pe": "trailingPE",
    "payout": "payoutRatio", "beta": "beta", "market_cap": "marketCap",
}
REQUIRED = ("Country", "Symbol", "AsOf", "Currency")
FUNDAMENTALS_TEMPLATE = ",".join((*REQUIRED, "Source", *FIELDS)) + "\n"
MAX_ROWS = 2000
MAX_AGE_DAYS = 550


def _country(value: str) -> str:
    names = {name.casefold(): name for name in MARKETS}
    country = names.get(value.strip().casefold())
    if country is None:
        raise ValueError("Country must be one of the app's listing-market names.")
    return country


def _currency(country: str, value: str) -> str:
    value = value.strip()
    allowed = MARKETS[country]["currency"].split(" / ")
    if value not in allowed:
        raise ValueError(f"Currency for {country} must be {' or '.join(allowed)}. Currency units are case-sensitive.")
    return value


def _reference(value: str) -> str | None:
    if not value.strip():
        return None
    if len(value) > 2000:
        raise ValueError("Source URL is too long.")
    try:
        url = urlsplit(value.strip())
    except ValueError as exc:
        raise ValueError("Source must be an HTTPS URL without embedded credentials.") from exc
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("Source must be an HTTPS URL without embedded credentials.")
    return value.strip()


def parse_fundamentals(uploaded) -> dict[tuple[str, str], dict]:
    """Parse a bounded CSV into (listing country, provider symbol) -> info.

    Requires dated statements within 550 days. No missing financial value is
    substituted with zero, and arbitrary input columns are never retained.
    """
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)
    try:
        frame = pd.read_csv(uploaded, dtype=str, keep_default_na=False, encoding="utf-8-sig", nrows=MAX_ROWS + 1)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError) as exc:
        raise ValueError("Fundamentals must be a valid UTF-8 CSV file.") from exc
    frame.columns = [str(c).strip() for c in frame.columns]
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError("Fundamentals CSV is missing columns: " + ", ".join(sorted(missing)))
    unknown = set(frame.columns) - set(REQUIRED) - set(FIELDS) - {"Source"}
    if unknown:
        raise ValueError("Unknown fundamentals columns; use the supplied template: " + ", ".join(sorted(unknown)))
    if len(frame) > MAX_ROWS:
        raise ValueError(f"Fundamentals CSV must contain at most {MAX_ROWS:,} rows.")
    if frame.empty:
        raise ValueError("Fundamentals CSV has no company rows.")
    today = datetime.now(timezone.utc).date()
    result: dict[tuple[str, str], dict] = {}
    for number, (_, row) in enumerate(frame.iterrows(), start=2):
        try:
            country = _country(row["Country"])
            symbols = resolve_symbols(row["Symbol"], country)
            if len(symbols) != 1:
                raise ValueError("Each row must name exactly one stock ticker.")
            key = (country, symbols[0])
            if key in result:
                raise ValueError("Duplicate country/ticker rows are not allowed.")
            try:
                as_of = date.fromisoformat(row["AsOf"].strip())
            except (ValueError, TypeError) as exc:
                raise ValueError("AsOf must be an ISO date such as YYYY-MM-DD.") from exc
            age = (today - as_of).days
            if age < 0:
                raise ValueError("AsOf cannot be in the future.")
            if age > MAX_AGE_DAYS:
                raise ValueError(f"Fundamentals are older than {MAX_AGE_DAYS} days; import a current statement.")
            info = {"currency": _currency(country, row["Currency"]),
                    "fundamentals_as_of": as_of.isoformat(), "fundamentals_source": "User import"}
            reference = _reference(row.get("Source", ""))
            if reference:
                info["fundamentals_reference"] = reference
            count = 0
            for field, output in FIELDS.items():
                value = row.get(field, "").strip()
                if value.casefold() in {"", "n/a", "na", "null", "none"}:
                    continue
                try:
                    number_value = float(value)
                except ValueError as exc:
                    raise ValueError(f"{field} must be a number or blank.") from exc
                if not math.isfinite(number_value):
                    raise ValueError(f"{field} must be finite.")
                if field == "market_cap" and number_value < 0:
                    raise ValueError("market_cap cannot be negative.")
                max_magnitude = 1e18 if field == "market_cap" else 1e9
                if abs(number_value) > max_magnitude:
                    raise ValueError(f"{field} is outside the supported numeric range.")
                info[output] = number_value
                count += 1
            if not count:
                raise ValueError("Supply at least one observed financial input; blanks are not evidence.")
            result[key] = info
        except ValueError as exc:
            raise ValueError(f"Fundamentals row {number}: {exc}") from exc
    return result


def apply_fundamentals(item: dict, values: dict) -> dict:
    """Return a new research item with supplied financials and recalculated metrics.

    The input's currency must match its actual quote unit, including GBp/GBP.
    Histories and news remain the same objects; neither is fabricated here.
    """
    info = dict(item.get("info") or {})
    quote_currency = str(info.get("currency") or item.get("metrics", {}).get("currency") or "")
    supplied_currency = values.get("currency")
    if quote_currency and quote_currency not in {"Unknown", "User specified"} and supplied_currency != quote_currency:
        raise ValueError("Fundamentals currency does not match the stock's price unit; convert and verify the source before importing.")
    info.update(values)
    prices = item.get("prices")
    if prices is not None and not prices.empty:
        metrics = get_metrics(prices, info)
        # CSV providers explicitly disclose synthesized/unadjusted close data.
        if info.get("price_adjusted") is False:
            metrics["price_adjusted"] = False
            metrics["return_basis"] = "unadjusted price"
    else:
        metrics = dict(item.get("metrics") or {})
        metrics.update({"currency": info.get("currency", "Unknown"),
                        "profit_margin": info.get("profitMargins"), "roe": info.get("returnOnEquity"),
                        "debt_eq": info.get("debtToEquity"), "revenue_growth": info.get("revenueGrowth"),
                        "pe": info.get("trailingPE"), "payout": info.get("payoutRatio"),
                        "market_cap": info.get("marketCap")})
    return {**item, "info": info, "metrics": metrics}
