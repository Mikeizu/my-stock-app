from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

import pytest
import requests

from providers import csv_market, load_news, load_news_bundle


def feed(items):
    xml = "<rss><channel>" + "".join(
        "<item>" + "".join(f"<{k}>{escape(v)}</{k}>" for k, v in item.items()) + "</item>"
        for item in items) + "</channel></rss>"
    class Response:
        content = xml.encode()
        def raise_for_status(self):
            pass
    return Response()


def article(title="Company reports growth", link="https://example.com/report", days=1, source="Publisher"):
    return {"title": title, "link": link, "source": source,
            "pubDate": format_datetime(datetime.now(timezone.utc) - timedelta(days=days))}


def test_news_merges_sources_deduplicates_and_exposes_provenance(monkeypatch):
    def fake_get(url, **kwargs):
        if "feeds.finance" in url:
            return feed([article(link="https://example.com/another-link")])
        return feed([article("Company reports growth - Publisher"),
                     article("Company plans expansion", "https://example.com/expansion")])
    monkeypatch.setattr("providers.requests.get", fake_get)
    bundle = load_news_bundle("Company", "MSFT", country="United States")
    assert len(bundle["articles"]) == 2
    assert len(bundle["queries"]) == 3
    assert not bundle["errors"]
    assert all(x["provider"] and x["query"] and x["published"] for x in bundle["articles"])
    assert all(x["status"] == "ok" for x in bundle["queries"])


def test_current_news_excludes_old_future_unknown_dates_and_unsafe_links(monkeypatch):
    unknown = article("Unknown date", "https://example.com/unknown")
    unknown["pubDate"] = "Not a date"
    response = feed([article(), article("Old", "https://example.com/old", days=30),
                     article("Future", "https://example.com/future", days=-1), unknown,
                     article("Unsafe", "javascript:alert(1)"),
                     article("Credentials in URL", "https://user:pass@example.com/item")])
    monkeypatch.setattr("providers.requests.get", lambda *a, **kw: response)
    result = load_news_bundle("Company", "MSFT", days=14)
    assert [x["title"] for x in result["articles"]] == ["Company reports growth"]


def test_news_partial_failure_is_visible_and_successful_feed_is_retained(monkeypatch):
    def fake_get(url, **kwargs):
        if "news.google.com" in url:
            raise requests.ConnectionError("Proxy denied")
        return feed([article()])
    monkeypatch.setattr("providers.requests.get", fake_get)
    result = load_news_bundle("Company", "MSFT")
    assert len(result["articles"]) == 1
    assert len(result["errors"]) == 2
    assert [q["status"] for q in result["queries"]] == ["unavailable", "unavailable", "ok"]


def test_all_failed_news_does_not_fabricate_headlines(monkeypatch):
    def denied(*a, **kw):
        raise requests.HTTPError("403 blocked")
    monkeypatch.setattr("providers.requests.get", denied)
    bundle = load_news_bundle("Company", "MSFT")
    assert bundle["articles"] == []
    assert len(bundle["errors"]) == 3
    with pytest.raises(requests.RequestException, match="403 blocked"):
        load_news("Company", "MSFT")


def test_nigeria_uses_regional_news_and_does_not_imply_yahoo_market_coverage(monkeypatch):
    calls = []
    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return feed([article("Nigerian issuer earnings")])
    monkeypatch.setattr("providers.requests.get", fake_get)
    bundle = load_news_bundle("Dangote Cement", "DANGCEM", country="Nigeria")
    assert len(calls) == 2
    assert all("news.google.com" in url and params["gl"] == "NG" for url, params in calls)
    assert len(bundle["articles"]) == 1


def test_invalid_xml_is_reported_as_feed_failure(monkeypatch):
    class Response:
        content = b"<not-closed"
        def raise_for_status(self):
            pass
    monkeypatch.setattr("providers.requests.get", lambda *a, **kw: Response())
    bundle = load_news_bundle("Company", "MSFT")
    assert len(bundle["errors"]) == 3
    assert bundle["articles"] == []


def test_zero_results_and_no_feed_errors_remain_distinct(monkeypatch):
    monkeypatch.setattr("providers.requests.get", lambda *a, **kw: feed([]))
    assert load_news("Company", "MSFT") == []
    bundle = load_news_bundle("Company", "MSFT")
    assert not bundle["errors"]
    assert all(q["status"] == "ok" and q["matched"] == 0 for q in bundle["queries"])


def test_csv_unsorted_duplicates_keep_last_supplied_observation():
    from io import StringIO
    data = StringIO("Date,Close\n2026-02-03,103\n2026-02-02,100\n2026-02-03,104\n2026-02-04,105\n")
    frame, _, _ = csv_market(data)
    assert frame["Close"].tolist() == [100, 104, 105]
    assert frame.index.is_monotonic_increasing
    assert frame.index.is_unique


def test_csv_infinite_prices_are_not_treated_as_real_market_observations():
    from io import StringIO
    data = StringIO("Date,Close\n2026-02-02,100\n2026-02-03,inf\n2026-02-04,-3\n")
    frame, _, _ = csv_market(data)
    assert frame["Close"].tolist() == [100]


def test_csv_metadata_distinguishes_raw_fallback_from_supplied_adjustments():
    from io import StringIO
    raw = StringIO("Date,Close\n2026-02-02,100\n2026-02-03,101\n")
    frame, info, _ = csv_market(raw)
    assert "Adj Close" in frame
    assert info["price_adjusted"] is False
    assert info["dividends_supplied"] is False
    adjusted = StringIO("Date,Close,Adj Close,Dividends\n2026-02-02,100,99,0\n2026-02-03,101,100,1\n")
    _, info, _ = csv_market(adjusted)
    assert info["price_adjusted"] is True
    assert info["dividends_supplied"] is True


def test_english_news_edition_fallback_keeps_selected_listing_country(monkeypatch):
    calls = []
    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return feed([])
    monkeypatch.setattr("providers.requests.get", fake_get)
    load_news_bundle("Toyota", "7203.T", country="Japan")
    google = [params for url, params in calls if "news.google.com" in url]
    assert all(p["gl"] == "JP" and p["ceid"] == "US:en" for p in google)


def test_ambiguous_short_ticker_query_uses_company_name(monkeypatch):
    calls = []
    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return feed([])
    monkeypatch.setattr("providers.requests.get", fake_get)
    load_news_bundle("Visa", "V")
    assert any('"Visa" "V"' in p.get("q", "") for _, p in calls)


def test_market_history_uses_local_cache_and_bounded_timeout(monkeypatch, tmp_path):
    import pandas as pd
    import yfinance
    import providers
    calls = []
    class Ticker:
        def __init__(self, symbol):
            assert symbol == "MSFT"
        def history(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame({"Close": [100, 101]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
        def get_info(self):
            return {"longName": "Microsoft"}
    monkeypatch.setattr(providers, "YAHOO_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(providers, "_YAHOO_CACHE_READY", False)
    monkeypatch.setattr(yfinance, "set_tz_cache_location", lambda path: calls.append(path))
    monkeypatch.setattr(yfinance, "Ticker", Ticker)
    prices, info, fetched = providers.load_market("MSFT")
    assert calls[0] == str(tmp_path / "cache")
    assert calls[1]["timeout"] == 12
    assert calls[1]["raise_errors"] is True
    assert len(prices) == 2 and info["longName"] == "Microsoft"
    assert fetched
