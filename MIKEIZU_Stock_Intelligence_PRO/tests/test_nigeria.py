"""Controlled import fixtures only; none are real NGX quotes."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pandas as pd
import pytest

from nigeria import (NGX_COMPANIES, NGXDataUnavailable, ngx_profile, ngx_search,
                     normalize_ngx_symbol, save_ng_market, load_ng_market)
from markets import MARKETS, belongs_to_market, market_symbols, resolve_symbols, search_companies


def sample_prices():
    dates = pd.bdate_range("2026-01-05", periods=4, name="Date")
    return pd.DataFrame({"Close": [100., 101., 102., 103.],
                         "Adj Close": [98., 99., 100., 101.], "Dividends": [0., 0., 1., 0.]}, index=dates)


def test_directory_is_names_and_sectors_not_invented_prices():
    assert len(NGX_COMPANIES) >= 25
    assert {"DANGCEM", "GTCO", "ZENITHBANK", "MTNN", "BUAFOODS", "SEPLAT"}.issubset(NGX_COMPANIES)
    assert all(set(row) == {"name", "sector", "source_url"} for row in NGX_COMPANIES.values())
    profile = ngx_profile("GTCO")
    assert profile["currency"] == "NGN"
    assert profile["directory_only"] is True
    assert "Guaranty" in profile["longName"]
    assert "price" not in profile


def test_local_discovery_never_requires_network(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Nigerian directory search must not call Yahoo")
    monkeypatch.setattr("markets.requests.get", unexpected)
    hits = search_companies("Guaranty", "Nigeria")
    assert hits == [{"symbol": "GTCO.NGX", "name": "Guaranty Trust Holding Company Plc", "exchange": "NGX", "country": "Nigeria"}]
    assert ngx_search("bank")
    assert ngx_search("GTCO.NGX")[0]["symbol"] == "GTCO.NGX"
    assert ngx_search("No such company") == []


def test_internal_namespace_never_maps_ngx_into_us():
    assert normalize_ngx_symbol(" gtco ") == "GTCO.NGX"
    assert resolve_symbols("GTCO,DANGCEM,GTCO.NGX", "Nigeria") == ["GTCO.NGX", "DANGCEM.NGX"]
    assert market_symbols("Nigeria")
    assert MARKETS["Nigeria"]["automatic_feed"] is False
    assert belongs_to_market("GTCO.NGX", "Nigeria")
    assert not belongs_to_market("GTCO", "Nigeria")
    assert not belongs_to_market("GTCO.NGX", "United States")
    with pytest.raises(ValueError):
        resolve_symbols("GTCO.NGX", "United States")
    with pytest.raises(ValueError):
        resolve_symbols("MSFT", "Nigeria")


@pytest.mark.parametrize("symbol", ["../GTCO", "GTCO/../../oops", "GTCO.L", "FAKE", "", "GTCO;cmd"])
def test_unknown_or_path_like_symbols_are_rejected(symbol):
    with pytest.raises(ValueError):
        normalize_ngx_symbol(symbol)


def test_missing_ng_data_stays_missing_and_does_not_touch_yahoo(monkeypatch, tmp_path):
    import nigeria
    import yfinance
    import providers
    monkeypatch.setattr(nigeria, "DATA_DIR", tmp_path)
    def unexpected(*args, **kwargs):
        pytest.fail("NGX must never be fetched as a Yahoo ticker")
    monkeypatch.setattr(yfinance, "Ticker", unexpected)
    with pytest.raises(NGXDataUnavailable, match="no authorized price history"):
        providers.load_market("GTCO.NGX")


def test_authorized_import_round_trip_preserves_dates_values_and_only_whitelisted_financials(tmp_path):
    frame = sample_prices()
    info = {"currency": "NGN", "price_adjusted": True, "dividends_supplied": True,
            "profitMargins": .2, "trailingPE": 8, "fundamentals_as_of": "2026-06-30",
            "api_key": "not-a-real-secret-test-fixture", "payoutRatio": .3}
    prices, loaded, fetched = save_ng_market("GTCO", frame, info, data_dir=tmp_path)
    pd.testing.assert_frame_equal(prices, frame, check_freq=False)
    assert loaded["profitMargins"] == .2
    assert loaded["payoutRatio"] == .3
    assert loaded["fundamentals_as_of"] == "2026-06-30"
    assert loaded["fundamentals_source"] == "User import"
    assert loaded["currency"] == "NGN"
    assert loaded["price_adjusted"] and loaded["dividends_supplied"]
    assert "api_key" not in loaded
    assert "api_key" not in (tmp_path / "GTCO.fundamentals.json").read_text()
    assert fetched
    again, _, _ = load_ng_market("GTCO.NGX", data_dir=tmp_path)
    pd.testing.assert_frame_equal(again, prices, check_freq=False)


def test_raw_import_does_not_promote_synthetic_adjustments_or_dividends(tmp_path):
    frame = sample_prices()
    _, info, _ = save_ng_market("MTNN", frame, {"price_adjusted": False, "dividends_supplied": False}, data_dir=tmp_path)
    retained = pd.read_csv(tmp_path / "MTNN.csv")
    assert list(retained.columns) == ["Date", "Close"]
    assert info["price_adjusted"] is False
    assert info["dividends_supplied"] is False


def test_wrong_currency_and_nonfinite_financials_do_not_get_saved(tmp_path):
    for info in [{"currency": "USD"}, {"profitMargins": float("inf")}, {"trailingPE": "bad"}]:
        with pytest.raises(ValueError):
            save_ng_market("MTNN", sample_prices(), info, data_dir=tmp_path)
    assert not list(tmp_path.iterdir())


def test_news_search_uses_real_ng_ticker_not_internal_suffix(monkeypatch):
    from providers import load_news_bundle
    calls = []
    class Response:
        content = b"<rss><channel></channel></rss>"
        def raise_for_status(self):
            pass
    def get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return Response()
    monkeypatch.setattr("providers.requests.get", get)
    result = load_news_bundle("Guaranty Trust Holding Company", "GTCO.NGX", country="Nigeria")
    assert len(calls) == 2
    assert all("news.google.com" in url and params["gl"] == "NG" for url, params in calls)
    assert all(".NGX" not in params["q"] for _, params in calls)
    assert any('"GTCO"' in params["q"] for _, params in calls)
    assert result["articles"] == []
