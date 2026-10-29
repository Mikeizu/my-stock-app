"""UI regressions use synthetic fixtures only; never presented as live data."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def widget(at, kind, label):
    return next(element for element in getattr(at, kind) if element.label == label)


def assert_clean(at):
    assert not at.exception, [e.message for e in at.exception]


@pytest.fixture
def app_factory(monkeypatch, tmp_path):
    import providers
    import markets
    import dashboard
    import storage

    st.cache_data.clear()
    monkeypatch.setattr(storage, "DB", tmp_path / "watchlist.sqlite3")
    calls = {"market": [], "news": [], "search": [], "news_fails": False,
             "market_fails": set(), "bearish": False}

    def market(symbol):
        calls["market"].append(symbol)
        if symbol in calls["market_fails"]:
            raise RuntimeError("Synthetic test price access denied for " + symbol)
        dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=650)
        x = np.arange(650)
        close = 80 * np.exp(x * .0004 + .035 * np.sin(x / 25))
        if calls["bearish"]:
            close = 80 * np.exp(x * -.001 + .01 * np.sin(x / 25))
        divs = np.zeros(650)
        divs[50::63] = .4
        if calls["bearish"]:
            divs[:] = 0
        prices = pd.DataFrame({"Close": close, "Adj Close": close * np.exp(x * .00005),
                               "Dividends": divs}, index=dates)
        currency = "NGN" if symbol.endswith(".NGX") else "GBP" if symbol.endswith(".L") else "CAD" if symbol.endswith(".TO") else "USD"
        info = {"longName": "Synthetic test issuer " + symbol, "currency": currency,
                "profitMargins": .22, "returnOnEquity": .2, "debtToEquity": 45,
                "revenueGrowth": .12, "earningsGrowth": .18, "trailingPE": 18,
                "payoutRatio": .5, "beta": .8, "sector": "Synthetic test sector"}
        if calls["bearish"]:
            info.update({"profitMargins": -.2, "returnOnEquity": -.1, "debtToEquity": 300,
                         "revenueGrowth": -.25, "earningsGrowth": -.3, "trailingPE": -5})
        return prices, info, datetime.now(timezone.utc).isoformat()

    def news(company, symbol, days=14, limit=18, country="United States"):
        calls["news"].append((symbol, country))
        if calls["news_fails"]:
            raise RuntimeError("Synthetic test news access denied")
        articles = [{"title": f"Synthetic test issuer {symbol} reports profit growth event {i}",
                     "link": f"https://example.com/{symbol}/test-{i}",
                     "published": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                     "source": "Synthetic test publisher", "provider": "Synthetic test feed"}
                    for i in range(5)]
        return {"articles": articles, "errors": [], "queries": [{"provider": "Synthetic test feed", "query": symbol}]}

    def search(query, country, limit=10):
        calls["search"].append((query, country))
        symbol = "GTCO.NGX" if country == "Nigeria" else "ADBE"
        return [{"symbol": symbol, "name": "Synthetic discovery test issuer", "exchange": "NGX" if country == "Nigeria" else "NASDAQ", "country": country}]

    monkeypatch.setattr(providers, "load_market", market)
    monkeypatch.setattr(providers, "load_news_bundle", news)
    monkeypatch.setattr(markets, "search_companies", search)
    monkeypatch.setattr(dashboard, "search_companies", search)

    def create():
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        assert_clean(at)
        return at, calls

    create.market = market
    create.news = news
    yield create
    st.cache_data.clear()


def choose_countries(at, countries):
    widget(at, "multiselect", "Countries to research").set_value(countries).run()
    assert_clean(at)


def run_scan(at, multi=False):
    if not multi:
        choose_countries(at, ["United States"])
    widget(at, "multiselect", "United States research basket").set_value(["MSFT", "AAPL"])
    if multi:
        widget(at, "multiselect", "Nigeria research basket").set_value(["DANGCEM.NGX"])
    widget(at, "button", "Run multi-country deep research").click().run()
    assert_clean(at)
    return at


def ranking(at):
    return next(df.value for df in at.dataframe if "Research score (%)" in df.value.columns)


def test_initial_ui_offers_nigeria_and_us_without_network_fetch(app_factory):
    at, calls = app_factory()
    assert widget(at, "multiselect", "Countries to research").value == ["Nigeria", "United States"]
    assert "United Kingdom" in widget(at, "multiselect", "Countries to research").options
    assert all(s.endswith(".NGX") for s in widget(at, "multiselect", "Nigeria research basket").value)
    assert widget(at, "multiselect", "United States research basket").value
    assert not calls["market"] and not calls["news"] and not calls["search"]


def test_company_search_adds_discovered_stock_to_correct_country_basket(app_factory):
    at, calls = app_factory()
    widget(at, "text_input", "Find companies in United States").set_value("Adobe")
    widget(at, "button", "Find stocks in United States").click().run()
    assert_clean(at)
    assert calls["search"] == [("Adobe", "United States")]
    assert widget(at, "multiselect", "Matching companies in United States").value == ["ADBE"]
    widget(at, "button", "Add selected United States companies").click().run()
    assert_clean(at)
    assert "ADBE" in widget(at, "multiselect", "United States research basket").value
    assert all(s.endswith(".NGX") for s in widget(at, "multiselect", "Nigeria research basket").value)


def test_scan_ranks_and_inspects_without_another_fetch(app_factory):
    at, calls = app_factory()
    run_scan(at)
    frame = ranking(at)
    assert set(frame["Ticker"]) == {"MSFT", "AAPL"}
    assert frame["Evidence sufficient"].all()
    assert frame["Research score (%)"].between(0, 100).all()
    assert frame["Data coverage (%)"].between(0, 100).all()
    assert set(calls["market"]) == {"MSFT", "AAPL"}
    selected = widget(at, "selectbox", "Inspect a researched stock")
    other = "United States::MSFT" if selected.value.endswith("AAPL") else "United States::AAPL"
    selected.set_value(other).run()
    assert_clean(at)
    assert at.session_state["research"]["id"] == other
    assert len(calls["market"]) == 2


def test_multi_country_scan_preserves_country_currency_and_indicators(app_factory):
    at, calls = app_factory()
    run_scan(at, multi=True)
    frame = ranking(at)
    assert set(frame["Country"]) == {"Nigeria", "United States"}
    assert len(frame) == 3
    nigeria = frame.loc[frame.Country == "Nigeria"].iloc[0]
    assert nigeria["Ticker"] == "DANGCEM.NGX" and nigeria["Currency"] == "NGN"
    assert set(frame["Indicator"]) <= {"BUY", "SELL", "NOT GOOD TO BUY", "WAIT FOR DATA"}
    assert len(widget(at, "selectbox", "Inspect a researched stock").options) == 3
    assert ("DANGCEM.NGX", "Nigeria") in calls["news"]


def test_country_selection_change_hides_unrelated_results_and_updates_tools(app_factory):
    at, calls = app_factory()
    run_scan(at)
    choose_countries(at, ["United Kingdom"])
    assert all(s.endswith(".L") for s in widget(at, "multiselect", "United Kingdom research basket").value)
    assert widget(at, "text_input", "Stock ticker to research").value.endswith(".L")
    assert not [df for df in at.dataframe if "Research score (%)" in df.value.columns]
    assert not [x for x in at.selectbox if x.label == "Inspect a researched stock"]
    assert len(calls["market"]) == 2


def test_news_failure_stays_visible_without_invented_evidence(app_factory):
    at, calls = app_factory()
    calls["news_fails"] = True
    run_scan(at)
    assert "Synthetic test news access denied" in " ".join(x.value for x in at.caption)
    assert at.session_state["research"]["news"]["count"] == 0
    frame = ranking(at)
    assert (frame["Headlines"] == 0).all()
    assert (frame["Data coverage (%)"] < 100).all()


def test_nigeria_missing_prices_keeps_regional_news_and_wait_indicator(app_factory):
    at, calls = app_factory()
    choose_countries(at, ["Nigeria"])
    widget(at, "multiselect", "Nigeria research basket").set_value(["DANGCEM.NGX"])
    calls["market_fails"].add("DANGCEM.NGX")
    widget(at, "button", "Run multi-country deep research").click().run()
    assert_clean(at)
    frame = ranking(at)
    assert frame.iloc[0]["Indicator"] == "WAIT FOR DATA"
    assert pd.isna(frame.iloc[0]["Close"])
    assert frame.iloc[0]["Currency"] == "NGN"
    assert frame.iloc[0]["Headlines"] == 5
    assert not frame.iloc[0]["Evidence sufficient"]
    assert any("Synthetic test price access denied" in x.value for x in at.warning)
    assert calls["market"] == ["DANGCEM.NGX"]
    assert calls["news"] == [("DANGCEM.NGX", "Nigeria")]


def test_strategy_recalculates_without_refetching_sources(app_factory):
    at, calls = app_factory()
    run_scan(at)
    widget(at, "selectbox", "Investment strategy").set_value("Growth").run()
    assert_clean(at)
    assert set(ranking(at)["Strategy"]) == {"Growth"}
    assert len(calls["market"]) == 2 and len(calls["news"]) == 2


def test_sell_indicator_is_only_enabled_for_existing_holdings(app_factory):
    at, calls = app_factory()
    calls["bearish"] = True
    run_scan(at)
    assert set(ranking(at)["Indicator"]) == {"NOT GOOD TO BUY"}
    widget(at, "toggle", "Review this basket as stocks I already own").set_value(True).run()
    assert_clean(at)
    assert set(ranking(at)["Indicator"]) == {"SELL"}
    assert len(calls["market"]) == 2 and len(calls["news"]) == 2


def test_deep_stock_selection_survives_later_tool_reruns(app_factory):
    at, calls = app_factory()
    run_scan(at)
    widget(at, "text_input", "Stock ticker to research").set_value("KO")
    widget(at, "button", "Analyse stock").click().run()
    assert_clean(at)
    assert at.session_state["research"]["symbol"] == "KO"
    widget(at, "select_slider", "Investment horizon").set_value(6).run()
    assert_clean(at)
    assert at.session_state["research"]["symbol"] == "KO"
    assert calls["market"].count("KO") == 1


def _csv_bytes(cadence="B"):
    dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=300) if cadence == "B" else pd.date_range(end=datetime.now(timezone.utc).date(), periods=300, freq="ME")
    return pd.DataFrame({"Date": dates, "Close": 100 + np.arange(300) * .03}).to_csv(index=False).encode()


def test_nigeria_csv_uses_same_ranking_with_no_invented_fundamentals(app_factory, monkeypatch):
    content = _csv_bytes()
    def uploaded(label, *args, **kwargs):
        if label == "Import Nigeria price CSVs (optional)":
            file = BytesIO(content)
            file.name = "DANGCEM.csv"
            return [file]
        return [] if kwargs.get("accept_multiple_files") else None
    monkeypatch.setattr(st, "file_uploader", uploaded)
    at, calls = app_factory()
    choose_countries(at, ["Nigeria"])
    widget(at, "multiselect", "Nigeria research basket").set_value([])
    widget(at, "button", "Run multi-country deep research").click().run()
    assert_clean(at)
    frame = ranking(at)
    assert frame.iloc[0]["Ticker"] == "DANGCEM.NGX"
    assert frame.iloc[0]["Country"] == "Nigeria" and frame.iloc[0]["Currency"] == "NGN"
    assert frame.iloc[0]["Indicator"] == "WAIT FOR DATA"
    assert not frame.iloc[0]["Evidence sufficient"]
    assert not calls["market"]
    assert calls["news"] == [("DANGCEM.NGX", "Nigeria")]


def test_nigeria_csv_and_dated_financials_are_combined_before_scoring(app_factory, monkeypatch):
    content = _csv_bytes()
    date = datetime.now(timezone.utc).date().isoformat()
    financials = ("Country,Symbol,AsOf,Currency,profit_margin,roe,debt_eq,revenue_growth,earnings_growth,pe,beta\n"
                  f"Nigeria,DANGCEM,{date},NGN,0.22,0.20,45,0.12,0.18,18,0.8\n").encode()
    def uploaded(label, *args, **kwargs):
        if label == "Import Nigeria price CSVs (optional)":
            file = BytesIO(content)
            file.name = "DANGCEM.csv"
            return [file]
        if label == "Fundamentals CSV for any selected countries":
            file = BytesIO(financials)
            file.name = "synthetic_financials.csv"
            return file
        return [] if kwargs.get("accept_multiple_files") else None
    monkeypatch.setattr(st, "file_uploader", uploaded)
    at, calls = app_factory()
    choose_countries(at, ["Nigeria"])
    widget(at, "multiselect", "Nigeria research basket").set_value([])
    widget(at, "button", "Run multi-country deep research").click().run()
    assert_clean(at)
    item = at.session_state["research"]
    assert item["metrics"]["profit_margin"] == .22
    assert item["metrics"]["roe"] == .20
    assert item["metrics"]["pe"] == 18
    assert item["info"]["fundamentals_source"] == "User import"
    assert item["info"]["fundamentals_as_of"] == date
    assert ranking(at).iloc[0]["Evidence sufficient"]
    assert ranking(at).iloc[0]["Indicator"] != "WAIT FOR DATA"
    assert not calls["market"]


def test_same_ticker_text_in_two_country_items_is_not_overwritten(app_factory):
    from workflow import assemble_item
    at, calls = app_factory()
    choose_countries(at, ["United States", "Canada"])
    items = []
    for country, currency in [("United States", "USD"), ("Canada", "CAD")]:
        prices, info, fetched = app_factory.market("ABC")
        info["currency"] = currency
        items.append(assemble_item("ABC", country, prices, info, fetched,
                                  lambda company, symbol, listing: app_factory.news(company, symbol, country=listing)))
    at.session_state["combined_scan"] = {"countries": ["United States", "Canada"], "items": items,
                                          "errors": [], "requested": 2, "checked": "Synthetic test run", "run_id": "identity-test"}
    at.run()
    assert_clean(at)
    frame = ranking(at)
    assert len(frame) == 2 and set(frame["Ticker"]) == {"ABC"}
    assert set(frame["Country"]) == {"United States", "Canada"}
    options = widget(at, "selectbox", "Inspect a researched stock")
    assert len(options.options) == 2
    options.set_value("Canada::ABC").run()
    assert_clean(at)
    assert at.session_state["research"]["country"] == "Canada"
    assert at.session_state["research"]["metrics"]["currency"] == "CAD"


def test_empty_country_selection_is_valid_and_does_not_fetch(app_factory):
    at, calls = app_factory()
    choose_countries(at, [])
    assert any("Select at least one country" in item.value for item in at.info)
    assert not calls["market"] and not calls["news"]
