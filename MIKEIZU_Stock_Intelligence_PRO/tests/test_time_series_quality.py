"""Synthetic regressions for history cadence and coherent return endpoints."""
import numpy as np
import pandas as pd
import pytest

from engine import backtest_sma, bootstrap_returns, closes, get_metrics


def daily_history(count=650):
    dates = pd.bdate_range("2022-01-03", periods=count)
    raw = 100 * np.exp(np.arange(count) * .0002)
    return pd.DataFrame({"Close": raw, "Adj Close": raw * .9,
                         "Dividends": np.zeros(count)}, index=dates)


@pytest.mark.parametrize("cadence", ["ME", "W-FRI"])
@pytest.mark.parametrize("operation", [get_metrics, bootstrap_returns, backtest_sma])
def test_non_daily_history_cannot_enter_daily_analytics(cadence, operation):
    dates = pd.date_range("2000-01-01", periods=300, freq=cadence)
    # Two percent per monthly/weekly row must never become two percent per day.
    history = pd.DataFrame({"Close": 100 * 1.02 ** np.arange(300)}, index=dates)
    with pytest.raises(ValueError, match="Daily closing-price history is required"):
        operation(history)


def test_old_adjusted_endpoint_falls_back_to_current_raw_history():
    history = daily_history()
    history.loc[history.index[-300:], "Adj Close"] = np.nan
    metrics = get_metrics(history)
    assert metrics["as_of"] == history.index[-1].date().isoformat()
    assert metrics["price_adjusted"] is False
    assert metrics["return_basis"] == "unadjusted price return"
    assert metrics["ret_12m"] == pytest.approx(history.Close.iloc[-1] / history.Close.iloc[-253] - 1)
    assert any("incomplete or stale" in x for x in metrics["data_warnings"])
    pd.testing.assert_series_equal(closes(history, adjusted=True), closes(history))


def test_one_invalid_adjusted_observation_does_not_drop_a_session():
    history = daily_history()
    history.loc[history.index[200], "Adj Close"] = 0
    chosen = closes(history, adjusted=True)
    assert len(chosen) == len(history)
    pd.testing.assert_series_equal(chosen, closes(history))


def test_nullable_adjusted_missing_value_is_not_treated_as_complete():
    history = daily_history()
    history["Adj Close"] = history["Adj Close"].astype("Float64")
    history.loc[history.index[-1], "Adj Close"] = pd.NA
    assert get_metrics(history)["price_adjusted"] is False
    pd.testing.assert_series_equal(closes(history, adjusted=True), closes(history))


def test_bootstrap_and_backtest_share_unadjusted_fallback():
    history = daily_history()
    history.loc[history.index[-50:], "Adj Close"] = np.nan
    raw_only = history.drop(columns="Adj Close")
    scenario = bootstrap_returns(history, horizon_months=1, trials=100)
    reference = bootstrap_returns(raw_only, horizon_months=1, trials=100)
    assert scenario["price_adjusted"] is False
    assert scenario["p10"] == pytest.approx(reference["p10"])
    assert scenario["median"] == pytest.approx(reference["median"])
    backtest = backtest_sma(history, window=100)
    assert backtest["price_adjusted"] is False
    pd.testing.assert_frame_equal(backtest["curve"], backtest_sma(raw_only, window=100)["curve"])


def test_explicit_synthetic_adjustment_flag_is_respected():
    history = daily_history()
    assert get_metrics(history, {"price_adjusted": False})["price_adjusted"] is False
    history.attrs["price_adjusted"] = False
    assert get_metrics(history)["price_adjusted"] is False
    assert bootstrap_returns(history, horizon_months=1, trials=100)["price_adjusted"] is False
    assert backtest_sma(history, window=100)["price_adjusted"] is False


def test_complete_adjusted_series_retains_total_return_basis():
    history = daily_history()
    metrics = get_metrics(history)
    assert metrics["price_adjusted"] is True
    assert metrics["return_basis"] == "adjusted total return"
    assert metrics["data_warnings"] == []
    assert bootstrap_returns(history, horizon_months=1, trials=100)["price_adjusted"] is True


def test_duplicate_unsorted_dates_do_not_double_count_dividends():
    history = daily_history(300)
    history.loc[history.index[-10], "Dividends"] = .5
    duplicate = history.iloc[[-10]].copy()
    duplicate["Dividends"] = .75
    mixed = pd.concat([history, duplicate]).iloc[::-1]
    # Last duplicate in the supplied order wins; chronological order is restored.
    metrics = get_metrics(mixed)
    assert metrics["observations"] == len(history)
    assert metrics["dividend_12m"] == pytest.approx(.5)
    assert closes(mixed).index.is_unique
    assert closes(mixed).index.is_monotonic_increasing


def test_nonnumeric_daily_closes_are_excluded_and_not_used_as_endpoints():
    history = daily_history(300)
    history.loc[history.index[-1], "Close"] = np.inf
    metrics = get_metrics(history)
    assert metrics["as_of"] == history.index[-2].date().isoformat()
    assert metrics["observations"] == len(history) - 1
    assert np.isfinite(metrics["price"])


def test_row_numbers_are_not_interpreted_as_nanosecond_dates():
    history = daily_history(300).reset_index(drop=True)
    with pytest.raises(ValueError, match="numeric row index"):
        get_metrics(history)


def test_daily_prices_with_weekends_and_a_few_holiday_closures_remain_valid():
    history = daily_history(300).drop(daily_history(300).index[[10, 20, 40, 100]])
    assert get_metrics(history)["observations"] == 296
    assert bootstrap_returns(history, horizon_months=1, trials=100)["samples"] == 100
