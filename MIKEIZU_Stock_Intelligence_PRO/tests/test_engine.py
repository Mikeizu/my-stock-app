import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import pytest
from engine import (normalize_symbol, get_metrics, sentiment_from_headlines,
                    evaluate, bootstrap_returns, backtest_sma)


def example_prices(days=650, dividend=True):
    # Synthetic series only for tests. Never displayed as current market data.
    dates = pd.bdate_range("2022-01-03", periods=days)
    close = 80 * np.exp(np.arange(days) * .0004 + .04*np.sin(np.arange(days)/25))
    adj = close * np.exp(.00005*np.arange(days))
    dividends = np.zeros(days)
    if dividend:
        dividends[50::63] = .40
    return pd.DataFrame({"Close":close, "Adj Close":adj,
                         "Dividends":dividends}, index=dates)


def test_normalize_symbol_rejects_injection():
    assert normalize_symbol(" brk-b ") == "BRK-B"
    with pytest.raises(ValueError): normalize_symbol("MSFT;rm -rf /")


def test_metrics_dividends_and_momentum():
    df = example_prices()
    m = get_metrics(df, {"longName":"Test", "currency":"USD", "payoutRatio":.5,
                         "trailingPE":20, "profitMargins":.18, "returnOnEquity":.25})
    assert 0 < m["yield_12m"] < .2
    assert m["price"] > 0
    assert m["ret_12m"] is not None
    assert m["sma200"] is not None


def test_missing_dividends_not_fabricated():
    df = example_prices().drop(columns=["Dividends"])
    m = get_metrics(df, {})
    assert m["yield_12m"] is None
    outcome = evaluate(m, {"average":None}, "Income")
    assert outcome["label"] != "RESEARCH CANDIDATE"


def test_headlines_deduplicated_and_negative_keyword():
    news = sentiment_from_headlines([
        {"title":"ABC cuts dividend after profit warning"},
        {"title":"ABC cuts dividend after profit warning"},
    ])
    assert news["count"] == 1
    assert news["average"] < -.5


def test_bootstrap_reproducible():
    x = bootstrap_returns(example_prices(), 6, trials=200)
    y = bootstrap_returns(example_prices(), 6, trials=200)
    assert x == y
    assert x["p10"] <= x["median"] <= x["p90"]


def test_backtest_returns_are_finite_and_no_future_signal():
    df = example_prices(450)
    result = backtest_sma(df, 100)
    assert np.isfinite(result["strategy"]["total_return"])
    assert len(result["curve"]) > 200
    # Past ending returns must not change when a future-only record is appended.
    tiny = df.iloc[:350].copy()
    first = backtest_sma(tiny, 100)["curve"]
    changed = tiny.copy()
    changed.loc[changed.index[-1] + pd.offsets.BDay(1)] = [1e6,1e6,0]
    later = backtest_sma(changed,100)["curve"].loc[first.index]
    pd.testing.assert_series_equal(first["SMA strategy"], later["SMA strategy"], check_freq=False)


def test_csv_missing_dividends_keeps_missing(tmp_path):
    from providers import csv_market
    p = tmp_path / "limited.csv"
    p.write_text("Date,Close\n2026-01-02,100\n2026-01-05,101\n", encoding="utf-8")
    with p.open("rb") as handle:
        frame, info, fetched = csv_market(handle, "Imported stock")
    assert "Dividends" not in frame.columns
    assert "Adj Close" in frame.columns
    assert info["longName"] == "Imported stock"


def test_dividend_yield_for_zero_payers_is_zero():
    m = get_metrics(example_prices(dividend=False), {})
    assert m["yield_12m"] == 0


def test_storage_save_update_remove(tmp_path, monkeypatch):
    import storage
    monkeypatch.setattr(storage, "DB", tmp_path / "saved.db")
    storage.save("KO", "Dividends", 50.)
    storage.save("KO", "Updated", 60.)
    items = storage.all_items()
    assert len(items) == 1
    assert items.loc[0, "thesis"] == "Updated"
    storage.remove("KO")
    assert storage.all_items().empty
