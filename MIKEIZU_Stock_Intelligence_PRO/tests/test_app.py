"""UI regressions use synthetic fixtures only; no fixture is presented as live data."""
from datetime import datetime, timedelta, timezone
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


@pytest.fixture
def app_factory(monkeypatch, tmp_path):
    import providers
    import markets
    import dashboard
    import storage

    st.cache_data.clear()
    monkeypatch.setattr(storage, "DB", tmp_path / "watchlist.sqlite3")
    calls = {"market": [], "news": [], "search": [], "news_fails": False}

    def market(symbol):
        calls["market"].append(symbol)
        # Synthetic daily close/dividend observations, ending at the current date.
        dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=650)
        x = np.arange(650)
        close = 80 * np.exp(x * .0004 + .035 * np.sin(x / 25))
        divs = np.zeros(650)
        divs[50::63] = .4
        prices = pd.DataFrame({"Close": close, "Adj Close": close * np.exp(x * .00005),
                               "Dividends": divs}, index=dates)
        info = {"longName": "Synthetic test issuer " + symbol, "currency": "GBP" if symbol.endswith(".L") else "USD",
                "profitMargins": .22, "returnOnEquity": .2, "debtToEquity": 45,
                "revenueGrowth": .12, "earningsGrowth": .18, "trailingPE": 18,
                "payoutRatio": .5, "beta": .8, "sector": "Synthetic test sector"}
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
        return [{"symbol": "ADBE", "name": "Synthetic discovery test issuer", "exchange": "NASDAQ", "country": country}]

    monkeypatch.setattr(providers, "load_market", market)
    monkeypatch.setattr(providers, "load_news_bundle", news)
    monkeypatch.setattr(markets, "search_companies", search)
    monkeypatch.setattr(dashboard, "search_companies", search)

    def create():
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        at.run()
        assert not at.exception, [e.message for e in at.exception]
        return at, calls

    yield create
    st.cache_data.clear()


def run_scan(at):
    widget(at, "multiselect", "Research basket").set_value(["MSFT", "AAPL"])
    widget(at, "button", "Run combined research").click().run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_initial_ui_has_country_selection_without_network_fetch(app_factory):
    at, calls = app_factory()
    assert widget(at, "selectbox", "Stock market / country").value == "United States"
    assert "Nigeria" in widget(at, "selectbox", "Stock market / country").options
    assert widget(at, "multiselect", "Research basket").value
    assert not calls["market"] and not calls["news"] and not calls["search"]


def test_company_search_adds_real_search_result_to_basket(app_factory):
    at, calls = app_factory()
    widget(at, "text_input", "Find a company or ticker").set_value("Adobe")
    widget(at, "button", "Find stocks").click().run()
    assert not at.exception
    assert calls["search"] == [("Adobe", "United States")]
    assert widget(at, "multiselect", "Matching companies").value == ["ADBE"]
    widget(at, "button", "Add selected companies to basket").click().run()
    assert not at.exception
    assert "ADBE" in widget(at, "multiselect", "Research basket").value


def test_combined_scan_ranks_and_inspects_without_another_fetch(app_factory):
    at, calls = app_factory()
    run_scan(at)
    ranking = next(df.value for df in at.dataframe if "Research score (%)" in df.value.columns)
    assert set(ranking["Ticker"]) == {"MSFT", "AAPL"}
    assert ranking["Evidence sufficient"].all()
    assert ranking["Research score (%)"].between(0, 100).all()
    assert ranking["Data coverage (%)"].between(0, 100).all()
    assert set(calls["market"]) == {"MSFT", "AAPL"}
    assert set(calls["news"]) == {("MSFT", "United States"), ("AAPL", "United States")}
    selected = widget(at, "selectbox", "Inspect a ranked stock")
    other = "MSFT" if selected.value == "AAPL" else "AAPL"
    selected.set_value(other).run()
    assert not at.exception
    assert at.session_state["research"]["symbol"] == other
    assert len(calls["market"]) == 2


def test_country_switch_hides_previous_country_rankings_and_changes_tickers(app_factory):
    at, calls = app_factory()
    run_scan(at)
    widget(at, "selectbox", "Stock market / country").set_value("United Kingdom").run()
    assert not at.exception
    assert all(s.endswith(".L") for s in widget(at, "multiselect", "Research basket").value)
    assert widget(at, "text_input", "Stock ticker to research").value.endswith(".L")
    assert not [df for df in at.dataframe if "Research score (%)" in df.value.columns]
    assert not [x for x in at.selectbox if x.label == "Inspect a ranked stock"]
    assert len(calls["market"]) == 2


def test_news_access_failure_is_visible_without_fabricated_headlines(app_factory):
    at, calls = app_factory()
    calls["news_fails"] = True
    run_scan(at)
    assert "Synthetic test news access denied" in " ".join(x.value for x in at.caption)
    assert at.session_state["research"]["news"]["count"] == 0
    ranking = next(df.value for df in at.dataframe if "Research score (%)" in df.value.columns)
    assert (ranking["Headlines"] == 0).all()
    assert (ranking["Data coverage (%)"] < 100).all()


def test_nigeria_offers_csv_without_us_quotes(app_factory):
    at, calls = app_factory()
    widget(at, "selectbox", "Stock market / country").set_value("Nigeria").run()
    assert not at.exception
    assert not [x for x in at.multiselect if x.label == "Research basket"]
    assert widget(at, "button", "Run combined research").disabled
    assert widget(at, "button", "Analyse stock").disabled
    assert widget(at, "text_input", "Stock ticker to research").value == ""
    assert any("NGX" in x.value and "CSV" in x.value for x in at.info)
    assert not calls["market"] and not calls["news"]


def test_strategy_recalculates_existing_evidence_without_refetch(app_factory):
    at, calls = app_factory()
    run_scan(at)
    widget(at, "selectbox", "Investment strategy").set_value("Growth").run()
    assert not at.exception
    ranking = next(df.value for df in at.dataframe if "Research score (%)" in df.value.columns)
    assert set(ranking["Strategy"]) == {"Growth"}
    assert len(calls["market"]) == 2 and len(calls["news"]) == 2


def test_deep_research_selection_survives_tools_reruns_after_scan(app_factory):
    at, calls = app_factory()
    run_scan(at)
    widget(at, "text_input", "Stock ticker to research").set_value("KO")
    widget(at, "button", "Analyse stock").click().run()
    assert not at.exception
    assert at.session_state["research"]["symbol"] == "KO"
    widget(at, "select_slider", "Investment horizon").set_value(6).run()
    assert not at.exception
    assert at.session_state["research"]["symbol"] == "KO"
    assert calls["market"].count("KO") == 1


def test_nigeria_csv_enters_same_ranking_without_invented_fundamentals(app_factory, monkeypatch):
    from io import BytesIO

    # AppTest has no upload setter; replace only the file-input boundary.
    dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=300)
    close = 100 + np.arange(300) * .03
    content = pd.DataFrame({"Date": dates, "Close": close}).to_csv(index=False).encode()

    def uploaded(label, *args, **kwargs):
        if kwargs.get("accept_multiple_files"):
            file = BytesIO(content)
            file.name = "DANGCEM.csv"
            return [file]
        return None

    monkeypatch.setattr(st, "file_uploader", uploaded)
    at, calls = app_factory()
    widget(at, "selectbox", "Stock market / country").set_value("Nigeria").run()
    widget(at, "text_area", "Company names for more relevant news (optional)").set_value("DANGCEM=Dangote Cement")
    widget(at, "button", "Run combined research").click().run()
    assert not at.exception, [e.message for e in at.exception]
    ranking = next(df.value for df in at.dataframe if "Research score (%)" in df.value.columns)
    assert ranking.iloc[0]["Ticker"] == "DANGCEM"
    assert ranking.iloc[0]["Country"] == "Nigeria"
    assert ranking.iloc[0]["Currency"] == "NGN"
    assert not ranking.iloc[0]["Evidence sufficient"]
    assert ranking.iloc[0]["Rating"] == "INSUFFICIENT / STALE DATA"
    assert not calls["market"]
    assert calls["news"] == [("DANGCEM", "Nigeria")]
