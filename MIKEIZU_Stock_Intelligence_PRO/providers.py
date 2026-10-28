"""Market & headline adapters. Fail visibly on missing/stale upstream data."""
from __future__ import annotations
from datetime import datetime, timezone
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
import html
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import requests
from engine import normalize_symbol
from markets import MARKETS

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 MIKEIZUStockResearch/2.0 (personal market research)"}
YAHOO_CACHE_DIR = Path(__file__).resolve().parent / "data" / "provider-cache"
_YAHOO_CACHE_LOCK = threading.Lock()
_YAHOO_CACHE_READY = False


def _prepare_yahoo_cache(yf) -> None:
    """Use yfinance's public cache hook once, before worker threads fetch data."""
    global _YAHOO_CACHE_READY
    with _YAHOO_CACHE_LOCK:
        if not _YAHOO_CACHE_READY:
            YAHOO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            yf.set_tz_cache_location(str(YAHOO_CACHE_DIR))
            _YAHOO_CACHE_READY = True


def load_market(symbol: str) -> tuple[pd.DataFrame, dict, str]:
    """yfinance is an unofficial personal-research source; see README."""
    import yfinance as yf
    _prepare_yahoo_cache(yf)
    sym = normalize_symbol(symbol)
    ticker = yf.Ticker(sym)
    prices = ticker.history(period="5y", interval="1d", auto_adjust=False, actions=True,
                            raise_errors=True, timeout=12)
    if prices is None or prices.empty:
        raise ValueError(f"No market history available for {sym}. Check exchange suffix and data rights.")
    prices = prices.copy()
    prices.index = pd.to_datetime(prices.index)
    if prices.index.tz is not None:
        prices.index = prices.index.tz_localize(None)
    prices = prices.sort_index()
    prices = prices[~prices.index.duplicated(keep="last")]
    try:
        info = ticker.get_info() or {}
    except Exception:
        info = {}
    return prices, info, datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_article_link(link: str) -> bool:
    try:
        parsed = urlsplit(link)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def _article_key(article: dict) -> str:
    # Google commonly appends a publisher to the title while ticker RSS does not.
    title = article["title"]
    publisher = article["source"]
    if publisher and title.casefold().endswith(" - " + publisher.casefold()):
        title = title[:-(len(publisher) + 3)]
    return re.sub(r"[^\w]+", " ", title.casefold()).strip()


def _canonical_link(link: str) -> str:
    parsed = urlsplit(link)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if not k.lower().startswith("utm_")]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _read_feed(url: str, params: dict, provider: str, query: str,
               cutoff: datetime, now: datetime) -> list[dict]:
    response = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=(5, 12))
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("News response exceeds the supported feed size.")
    root = ET.fromstring(response.content)
    articles = []
    for item in root.findall("./channel/item")[:80]:
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        if not title or not _safe_article_link(link):
            continue
        try:
            published = parsedate_to_datetime((item.findtext("pubDate") or "").strip())
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            published = published.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            # Undated evidence is not allowed to influence a current news score.
            continue
        if published < cutoff or published > now:
            continue
        source = html.unescape((item.findtext("source") or "").strip())
        if not source:
            source = urlsplit(link).hostname or provider
        articles.append({"title": title, "link": link,
            "published": published.isoformat(timespec="minutes"), "source": source,
            "provider": provider, "query": query})
    return articles


def load_news_bundle(company: str, symbol: str, days: int = 14, limit: int = 18,
                     country: str = "United States") -> dict:
    """Merge company, ticker/event and ticker-RSS searches with visible failures.

    These are dated headlines and links, not downloaded article bodies. A search
    can return irrelevant matches and cannot cover every story on the web.
    Unknown-date, future-date and out-of-window records do not enter scoring.
    """
    sym = normalize_symbol(symbol)
    market = MARKETS[country]
    days, limit = max(1, min(int(days), 90)), max(1, min(int(limit), 50))
    name = re.sub(r"[^\w .&'-]", " ", str(company or ""), flags=re.UNICODE).strip()
    if not name or name == "Unknown company":
        name = sym
    name = name[:80]
    region = market["news_region"]
    edition = market.get("news_edition", "US:en")
    company_query = f'"{name}" (stock OR shares OR earnings OR dividend) when:{days}d'
    ticker_identity = f'"{name}" "{sym}"' if len(sym.split(".")[0]) <= 2 and name != sym else f'"{sym}"'
    event_query = f'{ticker_identity} (earnings OR guidance OR dividend OR acquisition OR regulation) when:{days}d'
    feeds = [
        ("Google News · company", "https://news.google.com/rss/search",
         {"q": company_query, "hl": "en-US", "gl": region, "ceid": edition}, company_query),
        ("Google News · ticker/events", "https://news.google.com/rss/search",
         {"q": event_query, "hl": "en-US", "gl": region, "ceid": edition}, event_query),
    ]
    if market["supported"]:
        feeds.append(("Yahoo Finance RSS", "https://feeds.finance.yahoo.com/rss/2.0/headline",
                      {"s": sym, "region": region, "lang": "en-US"}, sym))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    articles, errors, queries = [], [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = [(label, url, query,
            pool.submit(_read_feed, url, params, label, query, cutoff, now))
            for label, url, params, query in feeds]
        for label, url, query, future in pending:
            try:
                found = future.result()
                articles.extend(found)
                queries.append({"provider": label, "query": query, "endpoint": url,
                                "status": "ok", "matched": len(found)})
            except (requests.RequestException, ET.ParseError, ValueError, TypeError) as exc:
                errors.append(f"{label}: {str(exc)[:240]}")
                queries.append({"provider": label, "query": query, "endpoint": url,
                                "status": "unavailable", "matched": 0})
    articles.sort(key=lambda x: x["published"], reverse=True)
    merged, titles, links = [], set(), set()
    for article in articles:
        title_key, link_key = _article_key(article), _canonical_link(article["link"])
        if title_key in titles or link_key in links:
            continue
        titles.add(title_key)
        links.add(link_key)
        merged.append(article)
        if len(merged) >= limit:
            break
    return {"articles": merged, "errors": errors, "queries": queries,
            "fetched": now.isoformat(timespec="seconds"), "days": days}


def load_news(company: str, symbol: str, days: int = 14, limit: int = 14,
              country: str = "United States") -> list[dict]:
    """Backwards-compatible headline list; new callers should inspect the bundle."""
    bundle = load_news_bundle(company, symbol, days, limit, country)
    if not bundle["articles"] and bundle["errors"] and all(q["status"] == "unavailable" for q in bundle["queries"]):
        raise requests.RequestException("; ".join(bundle["errors"]))
    return bundle["articles"]


def csv_market(uploaded, market_name: str = "CSV instrument") -> tuple[pd.DataFrame, dict, str]:
    """Local import for licensed/owned market data: Date, Close, optional Adj Close / Dividends."""
    frame = pd.read_csv(uploaded, nrows=20001)
    frame.columns = [str(c).strip() for c in frame.columns]
    adjustments_supplied = "Adj Close" in frame.columns
    dividends_supplied = "Dividends" in frame.columns
    if not {"Date", "Close"}.issubset(frame.columns):
        raise ValueError("CSV must contain Date and Close columns (optional Adj Close and Dividends).")
    if len(frame) > 20000: raise ValueError("CSV must be under 20,000 rows.")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce", utc=True)
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    frame["Close"] = frame["Close"].replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna(subset=["Date", "Close"])
    frame = frame[frame["Close"] > 0].copy()
    if frame.empty: raise ValueError("No valid positive closing prices in the uploaded CSV.")
    frame = frame.set_index("Date")
    frame.index = frame.index.tz_localize(None)
    frame = frame.sort_index(kind="stable")
    frame = frame[~frame.index.duplicated(keep="last")]
    if "Adj Close" not in frame:
        frame["Adj Close"] = frame["Close"]
    else:
        frame["Adj Close"] = pd.to_numeric(frame["Adj Close"], errors="coerce")
        frame["Adj Close"] = frame["Adj Close"].where(np.isfinite(frame["Adj Close"]) & (frame["Adj Close"] > 0))
    if "Dividends" in frame:
        frame["Dividends"] = pd.to_numeric(frame["Dividends"], errors="coerce").fillna(0)
    price_adjusted = adjustments_supplied and int(frame["Adj Close"].notna().sum()) >= 2
    return frame, {"longName": market_name, "currency": "User specified",
                   "price_adjusted": bool(price_adjusted),
                   "dividends_supplied": dividends_supplied}, datetime.now(timezone.utc).isoformat(timespec="seconds")
