"""Research assembly keeps country identity and missing-data boundaries intact."""
from datetime import datetime, timezone
from io import BytesIO

import numpy as np
import pandas as pd
import pytest

from workflow import assemble_item, fetch_research, import_research, instrument_key


def history(count=320):
    dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=count)
    close = 100 + np.arange(count) * .05
    return pd.DataFrame({"Close": close, "Adj Close": close * .95}, index=dates)


def no_news(*args):
    return {"articles": [], "errors": [], "queries": []}


def test_identity_includes_listing_country_even_for_same_ticker_text():
    assert instrument_key("Nigeria", "ABC") != instrument_key("United States", "ABC")


def test_price_failure_preserves_ngx_company_name_and_news():
    calls = []
    def unavailable(symbol):
        calls.append(("price", symbol))
        raise RuntimeError("Synthetic missing authorized price data")
    def news(company, symbol, country):
        calls.append(("news", symbol, country, company))
        return {"articles": [{"title": "Synthetic issuer update", "link": "https://example.com/test",
                               "source": "Synthetic publisher", "published": datetime.now(timezone.utc).isoformat()}],
                "errors": [], "queries": [{"query": company}]}
    item = fetch_research("DANGCEM", "Nigeria", unavailable, news)
    assert item["id"] == "Nigeria::DANGCEM.NGX"
    assert item["metrics"]["name"] == "Dangote Cement Plc"
    assert item["metrics"]["currency"] == "NGN"
    assert item["metrics"]["price"] is None
    assert item["metrics"]["observations"] == 0
    assert item["prices"].empty
    assert item["news"]["count"] == 1
    assert "Synthetic missing authorized" in item["price_error"]
    assert calls[0] == ("price", "DANGCEM.NGX")
    assert calls[1][1:3] == ("DANGCEM.NGX", "Nigeria")


def test_currency_mismatch_rejects_fundamentals_without_silent_conversion():
    financials = {("United States", "TEST"): {"currency": "NGN", "profitMargins": .3}}
    with pytest.raises(ValueError, match="does not match quote unit"):
        assemble_item("TEST", "United States", history(), {"currency": "USD"}, "test", no_news,
                      financials=financials)


def test_dated_fundamentals_merge_before_metrics_without_inventing_missing_inputs():
    supplied = {"currency": "NGN", "profitMargins": .25, "trailingPE": 12,
                "fundamentals_source": "User import", "fundamentals_as_of": datetime.now(timezone.utc).date().isoformat()}
    item = assemble_item("DANGCEM.NGX", "Nigeria", history(), {"currency": "NGN"}, "test", no_news,
                         financials={("Nigeria", "DANGCEM.NGX"): supplied})
    assert item["metrics"]["profit_margin"] == .25
    assert item["metrics"]["pe"] == 12
    assert item["metrics"]["roe"] is None
    assert item["info"]["fundamentals_source"] == "User import"


def test_monthly_csv_history_is_not_promoted_to_daily_quote_or_profit_inputs():
    dates = pd.date_range(end=datetime.now(timezone.utc).date(), periods=300, freq="ME")
    uploaded = BytesIO(pd.DataFrame({"Date": dates, "Close": 100 * 1.02 ** np.arange(300)}).to_csv(index=False).encode())
    uploaded.name = "DANGCEM.csv"
    item = import_research(uploaded, "Nigeria", {}, no_news)
    assert item["metrics"]["price"] is None
    assert item["metrics"]["ret_12m"] is None
    assert item["metrics"]["observations"] == 0
    assert "Daily closing-price history is required" in item["price_error"]


def test_synthetic_adjustment_metadata_reaches_series_and_analytics():
    prices = history()
    item = assemble_item("TEST", "United States", prices,
                         {"currency": "USD", "price_adjusted": False}, "test", no_news)
    assert item["prices"].attrs["price_adjusted"] is False
    assert item["metrics"]["price_adjusted"] is False
    assert item["metrics"]["return_basis"] == "unadjusted price return"
    assert item["metrics"]["data_warnings"]
    # Caller-owned frames are not mutated by assembly.
    assert "price_adjusted" not in prices.attrs


def test_stale_adjustment_is_not_overwritten_by_column_presence():
    prices = history()
    prices.loc[prices.index[-100:], "Adj Close"] = np.nan
    item = assemble_item("TEST", "United States", prices, {"currency": "USD"}, "test", no_news)
    assert item["metrics"]["price_adjusted"] is False
    assert item["metrics"]["as_of"] == prices.index[-1].date().isoformat()
    assert item["metrics"]["ret_12m"] == pytest.approx(prices.Close.iloc[-1] / prices.Close.iloc[-253] - 1)


def test_news_failure_does_not_erase_valid_price_observations():
    def unavailable(*args):
        raise RuntimeError("Synthetic news failure")
    item = assemble_item("TEST", "United States", history(), {"currency": "USD"}, "test", unavailable)
    assert item["metrics"]["price"] > 0
    assert item["news"]["count"] == 0
    assert item["news"]["average"] is None
    assert "Synthetic news failure" in item["news_error"]


def test_ngx_import_keeps_real_namespace_and_never_enters_yahoo(monkeypatch):
    import providers
    def unexpected(*args):
        pytest.fail("CSV import cannot fetch unrelated US market data")
    monkeypatch.setattr(providers, "load_market", unexpected)
    prices = history()
    uploaded = BytesIO(prices.rename_axis("Date").to_csv().encode())
    uploaded.name = "GTCO.csv"
    item = import_research(uploaded, "Nigeria", {}, no_news)
    assert item["symbol"] == "GTCO.NGX"
    assert item["metrics"]["name"] == "Guaranty Trust Holding Company Plc"
    assert item["metrics"]["currency"] == "NGN"
    assert item["source"] == "User-imported CSV"


def test_foreign_symbol_is_rejected_before_any_market_request():
    def unexpected(*args):
        pytest.fail("Foreign listing must be rejected before provider access")
    with pytest.raises(ValueError):
        fetch_research("MSFT", "Nigeria", unexpected, unexpected)
