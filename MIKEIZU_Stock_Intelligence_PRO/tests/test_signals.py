"""Synthetic, controlled evidence only; never presented as real stocks."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from engine import get_metrics
from signals import decision_signal, performance_report


def good_item():
    today = datetime.now(timezone.utc)
    return {
        "symbol": "TEST", "country": "United States", "info": {"earningsGrowth": .3, "beta": .8},
        "metrics": {"name": "Synthetic test stock", "as_of": today.date().isoformat(),
                    "observations": 600, "price": 120., "sma200": 100., "ret_6m": .3,
                    "ret_12m": .4, "profit_margin": .3, "roe": .3, "debt_eq": 30.,
                    "revenue_growth": .25, "yield_12m": .05, "payout": .5,
                    "pe": 14., "volatility": .2, "rsi": 55., "currency": "USD"},
        "news": {"items": [
            {"title": f"Synthetic earnings observation {i}", "link": f"https://example.test/story/{i}",
             "source": "Test source", "published": (today-timedelta(hours=1)).isoformat(), "sentiment": .4}
            for i in range(5)]},
    }


def price_item(days=800, daily_return=.0005, dividends=True):
    # Business-day synthetic data ending on the latest weekday.
    end = pd.Timestamp(datetime.now(timezone.utc).date())
    dates = pd.bdate_range(end=end, periods=days)
    values = 100 * np.exp(np.arange(days) * daily_return)
    frame = pd.DataFrame({"Close": values, "Adj Close": values}, index=dates)
    if dividends:
        frame["Dividends"] = 0.
        frame.loc[frame.index[30::63], "Dividends"] = .3
    info = {"currency": "USD", "price_adjusted": True}
    return {"prices": frame, "info": info, "metrics": get_metrics(frame, info), "news": {"items": []}}


def test_buy_requires_strong_current_evidence_and_trend():
    result = decision_signal(good_item())
    assert result["action"] == "BUY"
    assert result["score"] >= 72
    assert "BUY_RULES_MET" in result["reason_codes"]
    assert not result["blockers"]
    assert "not a calibrated" in result["note"]


def test_sell_is_only_an_existing_holder_exit_review():
    item = good_item()
    item["metrics"].update(price=70, ret_6m=-.3, ret_12m=-.5, profit_margin=.01,
                           roe=.02, debt_eq=300, revenue_growth=-.3, pe=40,
                           yield_12m=.001, payout=.8, volatility=.35)
    item["info"].update(earningsGrowth=-.4, beta=2)
    for article in item["news"]["items"]:
        article["sentiment"] = -.5
    assert decision_signal(item, holding=True)["action"] == "SELL"
    assert decision_signal(item, holding=False)["action"] == "NOT GOOD TO BUY"


@pytest.mark.parametrize("change", [
    {"as_of": "1999-01-01"}, {"observations": 40}, {"price": None},
    {"as_of": (datetime.now(timezone.utc).date()+timedelta(days=3)).isoformat()},
    {"daily_history_valid": False},
])
def test_incomplete_or_stale_evidence_never_becomes_buy_or_sell(change):
    item = good_item()
    item["metrics"].update(change)
    assert decision_signal(item, holding=True)["action"] == "WAIT FOR DATA"


def test_news_only_profile_has_no_trading_conclusion():
    result = decision_signal({"metrics": {"as_of": "Unavailable", "price": None, "observations": 0},
                              "price_error": "No data", "news": good_item()["news"]})
    assert result["action"] == "WAIT FOR DATA"
    assert result["blockers"]


@pytest.mark.parametrize("field,value", [
    ("yield_12m", .15), ("payout", 1.5), ("volatility", .65),
    ("debt_eq", -20), ("rsi", 90), ("profit_margin", -.1),
])
def test_risk_flags_prevent_buy_despite_other_positive_factors(field, value):
    item = good_item()
    item["metrics"][field] = value
    assert decision_signal(item)["action"] != "BUY"


@pytest.mark.parametrize("asof", [None, "bad-date", "1999-01-01", "2099-01-01"])
def test_imported_fundamental_dates_are_required_and_gated(asof):
    item = good_item()
    item["info"].update(fundamentals_source="User import", fundamentals_as_of=asof)
    assert decision_signal(item)["action"] == "WAIT FOR DATA"


def test_current_imported_fundamentals_can_support_research():
    item = good_item()
    item["info"].update(fundamentals_source="User import", fundamentals_as_of=item["metrics"]["as_of"])
    assert decision_signal(item)["action"] == "BUY"


def test_income_strategy_does_not_buy_when_cash_dividend_evidence_is_missing():
    item = good_item()
    item["metrics"]["yield_12m"] = None
    result = decision_signal(item, goal="Income")
    assert result["action"] != "BUY"
    assert "INCOME_NOT_ESTABLISHED" in result["reason_codes"]


def test_calendar_month_and_year_observed_returns_use_distinct_cutoffs():
    item = price_item()
    report = performance_report(item, include_scenarios=False)
    series = item["prices"]["Adj Close"]
    month = report["observed"]["month"]
    year = report["observed"]["year"]
    cutoff = series.index[-1] - pd.DateOffset(months=1)
    expected = series.iloc[-1] / series.loc[:cutoff].iloc[-1] - 1
    assert month["return"] == pytest.approx(expected)
    assert month["gross_gain"] == pytest.approx(expected * 10000)
    assert year["return"] != pytest.approx(month["return"] * 12)
    assert pd.Timestamp(year["start_date"]) <= series.index[-1] - pd.DateOffset(years=1)


def test_short_history_does_not_invent_monthly_or_annual_return():
    report = performance_report(price_item(days=10), include_scenarios=False)
    assert report["observed"] == {"month": None, "year": None}
    assert report["cagr"] is None
    assert report["income"] is None


def test_fees_reduce_profit_and_zero_return_still_has_costs():
    report = performance_report(price_item(daily_return=0), investment=10000, fee_pct=1, include_scenarios=False)
    month = report["observed"]["month"]
    assert month["gross_gain"] == 0
    assert month["net_gain"] == pytest.approx(10000 * (.99 / 1.01 - 1))


def test_complete_month_table_excludes_latest_observed_partial_month():
    item = price_item()
    report = performance_report(item, include_scenarios=False)
    last_period = item["prices"].index[-1].to_period("M")
    assert report["monthly_returns"]
    assert all(pd.Period(x["month"], freq="M") < last_period for x in report["monthly_returns"])
    assert len(report["monthly_returns"]) <= 24


def test_negative_scenarios_are_kept_as_losses_for_both_horizons():
    report = performance_report(price_item(daily_return=-.001), investment=20000)
    assert set(report["scenarios"]) == {"1m", "12m"}
    assert report["scenarios"]["1m"]["p90"] < 0
    assert report["scenarios"]["12m"]["net_p90"] < 0
    assert report["scenarios"]["1m"]["median"] != report["scenarios"]["12m"]["median"]


def test_zero_allocation_still_has_returns_but_zero_currency_gain():
    report = performance_report(price_item(), investment=0)
    assert report["observed"]["month"]["gross_gain"] == 0
    assert report["scenarios"]["1m"]["net_median"] == 0


def test_income_monthly_equivalent_is_labelled_not_a_payment_schedule():
    report = performance_report(price_item(), include_scenarios=False)
    income = report["income"]
    assert income["annual"] == pytest.approx(income["monthly_equivalent"] * 12)
    assert "not a monthly payment schedule" in income["note"]


def test_no_dividend_column_does_not_invent_income():
    report = performance_report(price_item(dividends=False), include_scenarios=False)
    assert report["income"] is None


def test_unadjusted_prices_are_explicitly_labelled():
    item = price_item()
    item["info"]["price_adjusted"] = False
    report = performance_report(item, include_scenarios=False)
    assert report["basis"] == "Unadjusted price returns"
    assert any("omit dividends" in warning for warning in report["warnings"])


@pytest.mark.parametrize("amount", [-1, float("inf"), float("nan")])
def test_invalid_allocations_rejected(amount):
    with pytest.raises(ValueError):
        performance_report(price_item(), investment=amount)


def test_stale_observed_history_is_dated_and_no_future_scenario_is_shown():
    item = price_item()
    item["prices"].index -= pd.DateOffset(years=3)
    report = performance_report(item)
    assert report["observed"]["year"] is not None
    assert not report["scenarios"]
    assert any("stale" in warning for warning in report["warnings"])


def test_news_only_profile_has_no_profit_calculations():
    report = performance_report({"metrics": {"currency": "NGN"}})
    assert report["currency"] == "NGN"
    assert report["observed"]["month"] is None
    assert not report["scenarios"]


def test_monthly_price_rows_cannot_generate_daily_profit_scenarios():
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=300, freq="ME")
    prices = pd.DataFrame({"Close": 100 * 1.02 ** np.arange(300)}, index=dates)
    report = performance_report({"prices": prices, "metrics": {"currency": "NGN"}})
    assert report["observed"] == {"month": None, "year": None}
    assert not report["scenarios"]
    assert any("Daily closing-price history" in warning for warning in report["warnings"])


def test_stale_adjusted_endpoint_uses_current_raw_series_with_warning():
    item = price_item()
    item["prices"].loc[item["prices"].index[-300:], "Adj Close"] = np.nan
    report = performance_report(item, include_scenarios=False)
    assert report["basis"] == "Unadjusted price returns"
    assert report["as_of"] == item["prices"].index[-1].date().isoformat()
    assert report["observed"]["month"] is not None
    assert any("Adjusted prices were not supplied or aligned" in warning for warning in report["warnings"])


def test_missing_entire_month_never_becomes_a_two_month_return_labelled_one_month():
    item = price_item()
    last_month = item["prices"].index[-1].to_period("M")
    missing = last_month - 4
    frame = item["prices"]
    item["prices"] = frame.loc[frame.index.to_period("M") != missing]
    report = performance_report(item, include_scenarios=False)
    months = {entry["month"] for entry in report["monthly_returns"]}
    assert str(missing) not in months
    assert str(missing + 1) not in months
    assert str(missing + 2) in months
