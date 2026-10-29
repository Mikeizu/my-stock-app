"""Explainable research indicators and honest historical/scenario profit views.

Signals are deterministic screening rules, not a validated prediction model.
Currency amounts describe a hypothetical allocation; no orders are submitted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

import pandas as pd

from engine import bootstrap_returns, closes, get_metrics, safe_float
from research import evaluate_unified, evidence_brief

RULE_VERSION = "3.0.0"
COLORS = {"BUY": "#31d5a4", "SELL": "#ff7385", "NOT GOOD TO BUY": "#f5b95a",
          "WAIT FOR DATA": "#8da9c4"}


def _date(value: Any):
    try:
        stamp = pd.Timestamp(value)
        return None if pd.isna(stamp) else stamp.date()
    except (ValueError, TypeError, OverflowError):
        return None


def decision_signal(item: dict, goal: str = "Balanced", holding: bool = False) -> dict:
    """Return BUY, holder-only SELL, NOT GOOD TO BUY or WAIT FOR DATA.

    BUY requires current eligible evidence, score >=72, a positive six-month
    return, price above its 200-day mean, and no enumerated distress flags.
    SELL requires an existing holder, eligible fresh evidence, score <55 and
    both a negative six-month return and price below the 200-day mean.
    Missing/stale data takes precedence over trading conclusions.
    """
    metrics, info, news = item.get("metrics") or {}, item.get("info") or {}, item.get("news") or {}
    result = evaluate_unified(metrics, news, info=info, goal=goal)
    brief = evidence_brief(metrics, news, info=info)
    blockers, reasons, codes, risks = [], [], [], []
    score = result["score"]
    now = datetime.now(timezone.utc).date()
    stamp = _date(metrics.get("as_of"))
    if stamp is None or stamp > now or (now - stamp).days > 7:
        blockers.append("Current closing-price evidence is missing, stale or future-dated.")
        codes.append("PRICE_DATE_UNUSABLE")
    if item.get("price_error"):
        blockers.append("The price source did not provide usable history.")
        codes.append("PRICE_SOURCE_UNAVAILABLE")
    if metrics.get("daily_history_valid") is False or metrics.get("cadence_valid") is False:
        blockers.append("The series is not a valid daily trading history.")
        codes.append("INVALID_TIME_SERIES")
    if result["label"] == "INSUFFICIENT / STALE DATA":
        blockers.extend(result["warnings"])
        codes.append("INSUFFICIENT_EVIDENCE")
    source = str(info.get("fundamentals_source") or "")
    if source.casefold().startswith("user"):
        financial_date = _date(info.get("fundamentals_as_of"))
        if financial_date is None or financial_date > now or (now - financial_date).days > 550:
            blockers.append("Imported fundamentals need a valid statement date within the past 550 days.")
            codes.append("IMPORTED_FUNDAMENTALS_DATE_UNUSABLE")

    price, sma, r6 = (safe_float(metrics.get(k)) for k in ("price", "sma200", "ret_6m"))
    upward = price is not None and sma is not None and price >= sma and r6 is not None and r6 > 0
    downward = price is not None and sma is not None and price < sma and r6 is not None and r6 < 0
    if upward:
        reasons.append(f"The latest close is above its 200-day average and the six-month return is {r6:+.1%}.")
        codes.append("POSITIVE_TREND")
    elif downward:
        risks.append(f"The latest close is below its 200-day average and the six-month return is {r6:+.1%}.")
        codes.append("NEGATIVE_TREND")
    else:
        reasons.append("The current price trend does not meet the positive-trend buying rule.")

    margin = safe_float(metrics.get("profit_margin"))
    payout = safe_float(metrics.get("payout"))
    yield_ = safe_float(metrics.get("yield_12m"))
    vol = safe_float(metrics.get("volatility"))
    debt = safe_float(metrics.get("debt_eq"))
    pe = safe_float(metrics.get("pe"))
    rsi = safe_float(metrics.get("rsi"))
    average_volume = safe_float(info.get("averageVolume"))
    guard = False
    checks = [
        (goal == "Income" and (yield_ is None or yield_ <= 0), "INCOME_NOT_ESTABLISHED", "An Income buying case requires an observed positive trailing cash-dividend yield."),
        (margin is None or margin <= 0, "PROFITABILITY_UNCONFIRMED", "Positive reported profit margins are not established."),
        (payout is not None and (payout < 0 or payout > 1), "PAYOUT_DISTRESS", "Reported dividends are outside 0–100% of earnings; check cash cover."),
        (yield_ is not None and yield_ > .09, "HIGH_YIELD_RISK", "The trailing dividend yield exceeds 9%; it may reflect distress or a special payment."),
        (vol is None or vol > .6, "VOLATILITY_RISK", "Historical volatility is missing or exceeds the buying-rule limit of 60% a year."),
        (debt is not None and debt < 0, "NEGATIVE_EQUITY", "Negative reported debt/equity requires balance-sheet review."),
        (pe is not None and pe <= 0, "NONPOSITIVE_EARNINGS", "Non-positive trailing P/E does not establish a profitable bargain."),
        (rsi is not None and rsi > 80, "EXTENDED_MOMENTUM", "RSI is above 80; this rule avoids buying an unusually extended price move."),
        (average_volume is not None and 0 <= average_volume < 10000, "LOW_REPORTED_VOLUME", "Reported average volume is under 10,000 shares; verify liquidity and spread."),
        (result["parts"].get("news") is not None and result["parts"]["news"] < 25,
         "ADVERSE_HEADLINES", "Recent headline tone is strongly negative; verify the original reports."),
    ]
    for condition, code, message in checks:
        if condition:
            guard = True
            codes.append(code)
            risks.append(message)
    if score is not None:
        reasons.append(f"Research evidence scores {score:.1f}/100 with {result['coverage']:.0%} input coverage.")
    if blockers:
        action = "WAIT FOR DATA"
        summary = "There is not enough current, usable evidence for a buy or sell conclusion. Update the missing data first."
    elif holding and result["eligible"] and score is not None and score < 55 and downward:
        action = "SELL"
        summary = "For an existing holding, weak evidence and a falling trend trigger an exit-review signal. Check costs, taxes and fresh issuer news before acting."
        codes.append("HOLDER_EXIT_REVIEW")
    elif result["eligible"] and score is not None and score >= 72 and upward and not guard:
        action = "BUY"
        summary = "This stock meets the current research buying rules: strong enough evidence, positive trend and no listed buying-rule risk flags. Verify the company reports and your risk budget."
        codes.append("BUY_RULES_MET")
    else:
        action = "NOT GOOD TO BUY"
        summary = "The current evidence does not meet this strategy's buying rules. Keep it under review rather than treating a high partial score as a buying reason."
        codes.append("BUY_RULES_NOT_MET")
    reasons.extend(risks[:3])
    return {
        "action": action, "color": COLORS[action], "summary": summary,
        "reasons": list(dict.fromkeys(reasons))[:6], "reason_codes": list(dict.fromkeys(codes)),
        "buy_case": brief["strengths"][:4], "sell_case": list(dict.fromkeys(risks + brief["risks"]))[:5],
        "blockers": list(dict.fromkeys(blockers)), "score": score, "coverage": result["coverage"],
        "rule_version": RULE_VERSION,
        "note": "A rule-based research indicator, not a calibrated profit probability or an automatically executed order.",
    }


def _gain(return_: float, investment: float, fee_pct: float) -> dict:
    fee = fee_pct / 100
    # Allocation includes the entry fee; exit fee is charged on proceeds.
    net_return = (1 + return_) * (1 - fee) / (1 + fee) - 1
    return {"return": return_, "gross_gain": investment * return_,
            "net_return": net_return, "net_gain": investment * net_return,
            "ending_value": investment * (1 + net_return)}


def _observed_period(series: pd.Series, offset: pd.DateOffset, investment: float, fee_pct: float):
    end = pd.Timestamp(series.index[-1])
    cutoff = end - offset
    if pd.Timestamp(series.index[0]) > cutoff:
        return None
    candidates = series.loc[:cutoff]
    if candidates.empty:
        return None
    start = pd.Timestamp(candidates.index[-1])
    if (cutoff - start).days > 7:
        return None
    ratio = safe_float(float(series.iloc[-1]) / float(candidates.iloc[-1]) - 1)
    if ratio is None:
        return None
    return {"start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
            **_gain(ratio, investment, fee_pct)}


def performance_report(item: dict, investment: float = 10000.0,
                       fee_pct: float = 0.0, include_scenarios: bool = True) -> dict:
    """Observed calendar returns and separately labelled historical-resampling scenarios.

    ``fee_pct`` is percentage points per entry and exit, not a spread or tax.
    Currency amounts are a fractional-share hypothetical allocation in the
    stock's native quote unit; currencies are never silently aggregated.
    """
    amount, cost = safe_float(investment), safe_float(fee_pct)
    if amount is None or amount < 0 or amount > 1e15:
        raise ValueError("Investment must be a finite amount from 0 to 1,000,000,000,000,000.")
    if cost is None or not 0 <= cost <= 100:
        raise ValueError("Fee must be a finite percentage from 0 to 100 per transaction.")
    metrics, info = item.get("metrics") or {}, item.get("info") or {}
    report = {"currency": str(metrics.get("currency") or info.get("currency") or "Unknown"),
              "as_of": metrics.get("as_of"), "investment": amount, "fee_pct": cost,
              "observed": {"month": None, "year": None}, "monthly_returns": [],
              "cagr": None, "income": None, "scenarios": {}, "warnings": [],
              "basis": "Unavailable",
              "note": "Historical gains apply today's hypothetical allocation to an observed period. Scenarios are not promised future profits. Fees are per entry/exit; taxes, slippage and FX are excluded."}
    prices = item.get("prices")
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        report["warnings"].append("No usable price history is available for performance calculations.")
        return report
    try:
        measured = get_metrics(prices, info)
        raw = closes(prices)
        adjusted = info.get("price_adjusted", measured.get("price_adjusted", "Adj Close" in prices))
        adjusted = bool(adjusted) and measured.get("price_adjusted", True)
        series = closes(prices, adjusted=adjusted)
    except (ValueError, TypeError, KeyError) as exc:
        report["warnings"].append("Performance calculation withheld: " + str(exc))
        return report
    if series.empty:
        report["warnings"].append("No usable closing-price series is available.")
        return report
    report["basis"] = "Dividend/split-adjusted returns" if adjusted else "Unadjusted price returns"
    if not adjusted:
        report["warnings"].append("Adjusted prices were not supplied or aligned. Returns may omit dividends or include split effects; no dividend is added to the price return.")
    last = pd.Timestamp(series.index[-1])
    report["as_of"] = last.date().isoformat()
    now = datetime.now(timezone.utc).date()
    if last.date() > now:
        report["warnings"].append("Future-dated history is not used for profit calculations.")
        return report
    report["observed"]["month"] = _observed_period(series, pd.DateOffset(months=1), amount, cost)
    report["observed"]["year"] = _observed_period(series, pd.DateOffset(years=1), amount, cost)
    if report["observed"]["month"] is None:
        report["warnings"].append("A full trailing calendar month of history is required for the monthly return.")
    if report["observed"]["year"] is None:
        report["warnings"].append("A full trailing calendar year of history is required for the annual return.")

    month_end = series.resample("ME").last().dropna()
    for i in range(1, len(month_end)):
        period = month_end.index[i].to_period("M")
        previous_period = month_end.index[i - 1].to_period("M")
        if previous_period + 1 != period:
            # Dropping an entirely missing month must not relabel a multi-month
            # change as one calendar month's return.
            continue
        # Never present the latest observed partial month as a completed month.
        if period >= last.to_period("M"):
            continue
        before = series.loc[:month_end.index[i - 1]]
        during = series.loc[(series.index > month_end.index[i - 1]) & (series.index <= month_end.index[i])]
        if before.empty or during.empty:
            continue
        start, end = pd.Timestamp(before.index[-1]), pd.Timestamp(during.index[-1])
        if ((month_end.index[i - 1] - start).days > 7
                or (month_end.index[i] - end).days > 7):
            continue
        value = safe_float(float(during.iloc[-1]) / float(before.iloc[-1]) - 1)
        if value is not None:
            report["monthly_returns"].append({"month": str(period), "start_date": start.date().isoformat(),
                                               "end_date": end.date().isoformat(), **_gain(value, amount, cost)})
    report["monthly_returns"] = report["monthly_returns"][-24:]
    first = pd.Timestamp(series.index[0])
    if first <= last - pd.DateOffset(years=1):
        years = (last - first).total_seconds() / (86400 * 365.2425)
        growth = float(series.iloc[-1]) / float(series.iloc[0])
        try:
            cagr = safe_float(growth ** (1 / years) - 1)
        except (ValueError, OverflowError, ZeroDivisionError):
            cagr = None
        if cagr is not None:
            report["cagr"] = {"annualized_return": cagr, "years": years,
                              "start_date": first.date().isoformat(), "end_date": last.date().isoformat()}
    cash_per_share = safe_float(measured.get("dividend_12m"))
    price = safe_float(measured.get("price"))
    if (cash_per_share is not None and cash_per_share >= 0 and price is not None and price > 0
            and first <= last - pd.DateOffset(years=1)):
        shares = math.floor(amount / (price * (1 + cost / 100)))
        cash = shares * cash_per_share
        report["income"] = {"shares": shares, "trailing_dividend_per_share": cash_per_share,
                            "annual": cash, "annual_run_rate": cash, "monthly_equivalent": cash / 12,
                            "note": "Assumes the observed trailing annual dividend repeats. Monthly equivalent is a budgeting average, not a monthly payment schedule or guaranteed profit."}
    fresh = 0 <= (now - last.date()).days <= 7
    if not fresh:
        report["warnings"].append("Prices are stale. Historical observations remain dated; future scenarios are withheld until prices are updated.")
    if include_scenarios and fresh:
        # Strip an untrusted/stale adjustment column when raw returns are the basis.
        scenario_prices = prices if adjusted else prices.drop(columns=["Adj Close"], errors="ignore")
        for months, key in ((1, "1m"), (12, "12m")):
            try:
                sim = bootstrap_returns(scenario_prices, horizon_months=months)
                report["scenarios"][key] = {**sim,
                    "p10_gain": _gain(sim["p10"], amount, cost)["net_gain"],
                    "median_gain": _gain(sim["median"], amount, cost)["net_gain"],
                    "p90_gain": _gain(sim["p90"], amount, cost)["net_gain"],
                    "net_p10": _gain(sim["p10"], amount, cost)["net_gain"],
                    "net_median": _gain(sim["median"], amount, cost)["net_gain"],
                    "net_p90": _gain(sim["p90"], amount, cost)["net_gain"],
                    "note": "Historical-resampling scenarios only; losses are possible and percentile bands are not calibrated future probabilities."}
            except (ValueError, TypeError) as exc:
                report["warnings"].append(f"{months}-month scenario unavailable: {exc}")
    return report
