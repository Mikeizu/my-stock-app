"""Country-aware research assembly. Missing prices never suppress news or become fake quotes."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from engine import get_metrics, sentiment_from_headlines
from markets import MARKETS, resolve_symbols
from providers import csv_market


def instrument_key(country: str, symbol: str) -> str:
    return country + "::" + symbol


def empty_metrics(info: dict) -> dict:
    fields = ("price ret_3m ret_6m ret_12m volatility sma50 sma200 rsi dividend_12m "
              "yield_12m dividend_years_of_4 dividend_events_12m pe payout debt_eq "
              "profit_margin roe revenue_growth market_cap").split()
    return {**dict.fromkeys(fields), "name": info.get("longName", "Unknown company"),
            "currency": info.get("currency", "Unknown"), "sector": info.get("sector", "Not supplied"),
            "as_of": "Unavailable", "observations": 0, "price_adjusted": False,
            "data_warnings": ["Usable daily price history is not available."]}


def assemble_item(symbol, country, prices, info, fetched, news_fetch, *, financials=None,
                  source="Yahoo Finance / yfinance", price_error=None):
    info = dict(info)
    imported = (financials or {}).get((country, symbol))
    if imported:
        actual = info.get("currency")
        if actual and actual != "Unknown" and actual != imported["currency"]:
            raise ValueError(f"Fundamental currency {imported['currency']} does not match quote unit {actual} for {symbol}.")
        info.update(imported)
    if prices is None:
        prices = pd.DataFrame()
    else:
        prices = prices.copy()
        if "price_adjusted" in info:
            prices.attrs["price_adjusted"] = bool(info["price_adjusted"])
    try:
        metrics = get_metrics(prices, info)
    except ValueError as exc:
        metrics = empty_metrics(info)
        price_error = str(exc) if not price_error else price_error
    try:
        bundle = news_fetch(metrics["name"], symbol, country)
    except Exception as exc:
        bundle = {"articles": [], "errors": [str(exc)[:280]], "queries": []}
    return {"id": instrument_key(country, symbol), "symbol": symbol, "country": country,
            "prices": prices, "info": info, "metrics": metrics, "fetched": fetched,
            "news": sentiment_from_headlines(bundle.get("articles", [])),
            "news_error": "; ".join(bundle.get("errors", [])),
            "news_queries": bundle.get("queries", []), "source": source,
            "price_error": price_error}


def fetch_research(symbol, country, market_fetch, news_fetch, financials=None):
    symbols = resolve_symbols(symbol, country)
    if len(symbols) != 1:
        raise ValueError("Research one valid stock ticker at a time.")
    symbol = symbols[0]
    if country == "Nigeria":
        from nigeria import ngx_profile
        fallback = ngx_profile(symbol)
        source = "Retained authorized NGX data"
    else:
        fallback = {"longName": symbol, "currency": MARKETS[country]["currency"].split(" / ")[0]}
        source = "Yahoo Finance / yfinance (unofficial, potentially delayed)"
    price_error = None
    try:
        prices, info, fetched = market_fetch(symbol)
        info = {**fallback, **info}
    except Exception as exc:
        prices, info = pd.DataFrame(), fallback
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        price_error = str(exc)[:350]
        source = "No price history available"
    return assemble_item(symbol, country, prices, info, fetched, news_fetch,
                         financials=financials, source=source, price_error=price_error)


def import_research(uploaded, country, names, news_fetch, financials=None,
                    currency=None, remember=False):
    label = Path(uploaded.name).stem.strip()
    symbols = resolve_symbols(label, country)
    if len(symbols) != 1:
        raise ValueError("Name each CSV after a single valid exchange ticker.")
    symbol = symbols[0]
    if country == "Nigeria":
        from nigeria import ngx_profile
        profile = ngx_profile(symbol)
    else:
        profile = {"longName": names.get(label.upper(), symbol)}
    uploaded.seek(0)
    prices, info, fetched = csv_market(uploaded, names.get(label.upper(), profile["longName"]))
    info.update({**profile, "currency": currency or MARKETS[country]["currency"].split(" / ")[0]})
    item = assemble_item(symbol, country, prices, info, fetched, news_fetch,
                         financials=financials, source="User-imported CSV")
    if remember and country == "Nigeria":
        if item["price_error"]:
            raise ValueError("Cannot retain invalid price history: " + item["price_error"])
        from nigeria import save_ng_market
        save_ng_market(symbol, item["prices"], item["info"])
    return item
