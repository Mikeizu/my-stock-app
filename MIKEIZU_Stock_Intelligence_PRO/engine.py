"""Deterministic research, ranking and risk tools. No order execution."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Any
import numpy as np
import pandas as pd

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^=]{0,17}$")
POS_WORDS = {
    "dividend increase": 0.45, "dividend hike": 0.45,
    "raises dividend": 0.45, "profit beats": 0.32,
    "beats earnings": 0.30, "raises guidance": 0.4,
    "record revenue": 0.25, "share buyback": 0.22,
    "earnings beat": 0.32, "profit growth": 0.25,
}
NEG_WORDS = {
    "dividend cut": -0.8, "cuts dividend": -0.8,
    "suspends dividend": -0.95, "profit warning": -0.7,
    "fraud investigation": -0.75, "sec investigation": -0.65,
    "misses earnings": -0.35, "guidance cut": -0.5,
    "earnings miss": -0.35, "debt default": -0.8,
    "bankruptcy": -0.95, "restatement": -0.4,
}


def normalize_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Use a valid stock ticker, e.g. MSFT, KO, BRK-B or a supported exchange suffix.")
    return symbol


def safe_float(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError, OverflowError):
        return None


def clip(value: float, lo: float = 0, hi: float = 100) -> float:
    return float(np.clip(value, lo, hi))


def _clean_daily_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """Normalize daily dates once, keeping the last supplied duplicate row.

    Numeric indexes are not dates: silently treating row numbers as nanosecond
    timestamps can make an arbitrary table look like high-frequency history.
    This helper does not create missing sessions or fill missing prices.
    """
    if prices.empty or "Close" not in prices:
        return pd.DataFrame()
    if not isinstance(prices.index, pd.DatetimeIndex):
        if pd.api.types.is_numeric_dtype(prices.index.dtype):
            raise ValueError("Price history requires dated daily observations, not a numeric row index.")
        dates = pd.to_datetime(prices.index, errors="coerce")
    else:
        dates = prices.index
    if not isinstance(dates, pd.DatetimeIndex):
        raise ValueError("Price history requires a consistent daily date index.")
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    frame = prices.copy()
    frame.index = dates.normalize()
    frame = frame[frame.index.notna()].sort_index(kind="stable")
    frame = frame[~frame.index.duplicated(keep="last")]
    raw = pd.to_numeric(frame["Close"], errors="coerce")
    frame = frame.loc[np.isfinite(raw) & (raw > 0)].copy()
    frame["Close"] = raw.loc[frame.index].astype(float)
    return frame


def _require_daily_history(series: pd.Series) -> None:
    """Reject weekly/monthly inputs before any daily annualization or resampling.

    Daily exchange data includes weekends and holidays. A four-calendar-day
    median threshold tolerates those closures, while a sparse-interval check
    prevents a mixture of daily and mostly weekly observations slipping through.
    This is a cadence check, not a complete exchange-calendar validation.
    """
    if len(series) < 2:
        raise ValueError("Not enough historical price observations for analysis.")
    gaps = series.index.to_series().diff().dt.total_seconds().dropna() / 86400
    if float(gaps.median()) > 4 or float((gaps > 4).mean()) > .2:
        raise ValueError("Daily closing-price history is required; weekly, monthly or sparse observations cannot be treated as trading days.")


def _price_inputs(prices: pd.DataFrame, *, adjusted_allowed: bool = True
                  ) -> tuple[pd.DataFrame, pd.Series, pd.Series, bool, list[str]]:
    frame = _clean_daily_frame(prices)
    if frame.empty:
        empty = pd.Series(dtype=float)
        return frame, empty, empty, False, []
    raw = frame["Close"].copy()
    chosen, is_adjusted, warnings = raw, False, []
    if adjusted_allowed and prices.attrs.get("price_adjusted", True) and "Adj Close" in frame:
        candidate = pd.to_numeric(frame["Adj Close"], errors="coerce")
        valid = (np.isfinite(candidate) & (candidate > 0)).fillna(False)
        if bool(valid.all()):
            chosen, is_adjusted = candidate.astype(float), True
        else:
            warnings.append("Adjusted closing prices are incomplete or stale; the entire return series uses unadjusted closes, so dividends or split effects may be omitted.")
    else:
        warnings.append("No validated adjusted closing-price series was supplied; returns use unadjusted prices and may omit dividends or include split distortions.")
    return frame, raw, chosen, is_adjusted, warnings


def closes(prices: pd.DataFrame, adjusted: bool = False) -> pd.Series:
    """Return one coherent dated series; never use an old adjusted endpoint."""
    _, raw, selected, _, _ = _price_inputs(prices)
    return selected if adjusted else raw


def get_metrics(prices: pd.DataFrame, info: dict[str, Any] | None = None) -> dict[str, Any]:
    info = info or {}
    frame, raw, adj, price_adjusted, data_warnings = _price_inputs(
        prices, adjusted_allowed=info.get("price_adjusted", True) is not False,
    )
    _require_daily_history(raw)
    last = float(raw.iloc[-1])
    def ret(days: int) -> float | None:
        if len(adj) <= days:
            return None
        return float(adj.iloc[-1] / adj.iloc[-days - 1] - 1)
    daily = adj.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    vol = safe_float(daily.tail(252).std() * np.sqrt(252)) if len(daily) > 20 else None
    sma50 = safe_float(raw.tail(50).mean()) if len(raw) >= 50 else None
    sma200 = safe_float(raw.tail(200).mean()) if len(raw) >= 200 else None
    change = raw.diff().dropna()
    gain = change.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    if len(change) >= 15:
        g, l = float(gain.iloc[-1]), float(loss.iloc[-1])
        rsi = 100 if l == 0 and g > 0 else (50 if l == 0 else 100-100/(1+g/l))
    else:
        rsi = None

    if "Dividends" in frame:
        divs = pd.to_numeric(frame["Dividends"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0).clip(lower=0)
        threshold = divs.index[-1] - pd.DateOffset(years=1)
        trailing_div = float(divs.loc[divs.index > threshold].sum())
        annual = divs.resample("YE").sum()
        # Last full year, not incomplete current calendar year
        full_years = annual[annual.index.year < divs.index[-1].year]
        stable_years = int((full_years.tail(4) > 0).sum())
        div_events = int((divs.loc[divs.index > threshold] > 0).sum())
    else:
        trailing_div, stable_years, div_events = None, None, None
    dividend_yield = (trailing_div / last) if trailing_div is not None and last > 0 else None
    last_date = pd.Timestamp(raw.index[-1]).date()
    pe = safe_float(info.get("trailingPE"))
    payout = safe_float(info.get("payoutRatio"))
    debt_eq = safe_float(info.get("debtToEquity"))
    profit_margin = safe_float(info.get("profitMargins"))
    roe = safe_float(info.get("returnOnEquity"))
    growth = safe_float(info.get("revenueGrowth"))
    asset_name = str(info.get("longName") or info.get("shortName") or "Unknown company")
    return {
        "name": asset_name, "currency": str(info.get("currency") or "Unknown"),
        "sector": str(info.get("sector") or "Not supplied"), "price": last,
        "as_of": last_date.isoformat(), "observations": len(raw),
        "ret_3m": ret(63), "ret_6m": ret(126), "ret_12m": ret(252),
        "volatility": vol, "sma50": sma50, "sma200": sma200, "rsi": rsi,
        "dividend_12m": trailing_div, "yield_12m": dividend_yield,
        "dividend_years_of_4": stable_years, "dividend_events_12m": div_events,
        "pe": pe, "payout": payout, "debt_eq": debt_eq, "profit_margin": profit_margin,
        "roe": roe, "revenue_growth": growth,
        "market_cap": safe_float(info.get("marketCap")),
        "price_adjusted": price_adjusted,
        "return_basis": "adjusted total return" if price_adjusted else "unadjusted price return",
        "data_warnings": data_warnings,
    }


def sentiment_from_headlines(articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Simple, explicitly non-LLM *headline-only* sentiment heuristic."""
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
    except ImportError:
        analyzer = None
    items = []
    seen = set()
    for item in articles:
        title = str(item.get("title") or "").strip()
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        score = analyzer.polarity_scores(title)["compound"] if analyzer else 0.0
        lowered = title.lower()
        score += sum(val for phrase, val in POS_WORDS.items() if phrase in lowered)
        score += sum(val for phrase, val in NEG_WORDS.items() if phrase in lowered)
        score = float(np.clip(score, -1, 1))
        items.append({**item, "sentiment": score,
                      "tone": "Positive" if score > .15 else ("Negative" if score < -.15 else "Mixed/neutral")})
    average = float(np.mean([x["sentiment"] for x in items])) if items else None
    return {"average": average, "count": len(items), "items": items}


def evaluate(metrics: dict[str, Any], news: dict[str, Any] | None, goal: str = "Balanced") -> dict[str, Any]:
    """Transparent, heuristic evidence score, NOT expected return or probability."""
    goal = goal if goal in {"Income", "Growth", "Balanced"} else "Balanced"
    weights = {
        "Income": {"income": 40, "quality": 30, "momentum": 10, "valuation": 10, "news": 10},
        "Growth": {"income": 5, "quality": 30, "momentum": 35, "valuation": 15, "news": 15},
        "Balanced": {"income": 25, "quality": 30, "momentum": 25, "valuation": 10, "news": 10},
    }[goal]
    aspects: dict[str, float | None] = {}
    y = metrics.get("yield_12m")
    p = metrics.get("payout")
    if y is not None:
        income = clip(y * 100 * 16)
        if y > .09: income = min(income, 30)  # high yield can be a distress signal
        if p is not None:
            income = .7 * income + .3 * (85 if .2 <= p <= .75 else 20 if p > 1 or p < 0 else 50)
        aspects["income"] = income
    else:
        aspects["income"] = None

    qs = []
    margin = metrics.get("profit_margin")
    roe = metrics.get("roe")
    leverage = metrics.get("debt_eq")
    growth = metrics.get("revenue_growth")
    if margin is not None: qs.append(clip(40 + margin * 170))
    if roe is not None: qs.append(clip(35 + roe * 150))
    if leverage is not None: qs.append(clip(100 - max(0, leverage - 50) * .33))
    if growth is not None: qs.append(clip(50 + growth * 170))
    aspects["quality"] = float(np.mean(qs)) if qs else None

    ms = []
    r6 = metrics.get("ret_6m")
    r12 = metrics.get("ret_12m")
    if r6 is not None: ms.append(clip(50 + r6 * 110))
    if r12 is not None: ms.append(clip(50 + r12 * 65))
    if metrics.get("sma200") is not None:
        ms.append(75 if metrics["price"] >= metrics["sma200"] else 25)
    aspects["momentum"] = float(np.mean(ms)) if ms else None

    pe = metrics.get("pe")
    aspects["valuation"] = None if pe is None else (10 if pe <= 0 else clip(100 - (pe - 12) * 2.1))
    n = news.get("average") if news else None
    aspects["news"] = None if n is None else clip(50 + n * 45)
    available = [k for k in weights if aspects[k] is not None]
    coverage = sum(weights[k] for k in available) / 100
    score = (sum(aspects[k] * weights[k] for k in available) /
             sum(weights[k] for k in available)) if available else None
    warnings = []
    if metrics.get("observations", 0) < 200:
        warnings.append("Limited price history")
    try:
        if (datetime.now(timezone.utc).date() - datetime.fromisoformat(metrics["as_of"]).date()).days > 7:
            warnings.append("Stale market prices")
    except (KeyError, ValueError):
        warnings.append("Price timestamp missing")
    if y is not None and y > .09: warnings.append("High dividend yield can signal a price collapse or an unsustainable payout")
    if p is not None and (p > 1 or p < 0): warnings.append("Earnings payout ratio is outside a sustainable range")
    if metrics.get("volatility") is not None and metrics["volatility"] > .6: warnings.append("High historical volatility")
    if goal == "Income" and (y is None or y <= 0): warnings.append("No confirmed dividend yield from available price history")
    if coverage < .6 or metrics.get("observations", 0) < 200 or "Stale market prices" in warnings:
        label = "INSUFFICIENT / STALE DATA"
    elif score is not None and score >= 72 and not (goal == "Income" and (y is None or y <= 0)):
        label = "RESEARCH CANDIDATE"
    elif score is not None and score >= 55:
        label = "WATCH / COMPARE"
    else:
        label = "CAUTION / REVIEW"
    return {"score": score, "coverage": coverage, "label": label,
            "parts": aspects, "weights": weights, "warnings": warnings, "goal": goal}


def bootstrap_returns(prices: pd.DataFrame, horizon_months: int = 6,
                      trials: int = 1000, seed: int = 41) -> dict[str, Any]:
    """Historical 5-day block resampling; a *scenario*, not calibrated prediction."""
    _, _, prices_adj, price_adjusted, data_warnings = _price_inputs(prices)
    _require_daily_history(prices_adj)
    if len(prices_adj) < 252:
        raise ValueError("At least 252 historical daily prices required for scenario modelling.")
    returns = np.log(prices_adj / prices_adj.shift(1)).replace([np.inf, -np.inf], np.nan).dropna().tail(756).to_numpy()
    if len(returns) < 250:
        raise ValueError("Not enough valid daily returns.")
    months = int(horizon_months)
    if not 1 <= months <= 24:
        raise ValueError("Horizon must be between 1 and 24 months.")
    steps = round(months * 21)
    rng = np.random.default_rng(seed)
    block_size = 5
    starts = rng.integers(0, len(returns) - block_size + 1, size=(trials, math.ceil(steps/block_size)))
    blocks = returns[starts[..., None] + np.arange(block_size)]
    paths = blocks.reshape(trials, -1)[:, :steps]
    projected = np.exp(paths.sum(axis=1)) - 1
    p10, p50, p90 = np.percentile(projected, [10, 50, 90]).tolist()
    return {"p10": p10, "median": p50, "p90": p90,
            "positive_fraction": float((projected > 0).mean()),
            "samples": trials, "months": months, "history_days": len(returns),
            "method": "5-day block bootstrap of trailing up to 756 " + ("adjusted" if price_adjusted else "unadjusted") + " daily returns",
            "price_adjusted": price_adjusted,
            "return_basis": "adjusted total return" if price_adjusted else "unadjusted price return",
            "data_warnings": data_warnings}


def backtest_sma(prices: pd.DataFrame, window: int = 200, trading_cost: float = .0015) -> dict[str, Any]:
    """Signal set at day close, position acts on NEXT trading day's return."""
    _, raw, adj, price_adjusted, data_warnings = _price_inputs(prices)
    _require_daily_history(raw)
    df = pd.concat([adj.rename("adjusted"), raw.rename("close")], axis=1).dropna()
    if len(df) < window + 40:
        raise ValueError(f"Need at least {window+40} trading days for this backtest.")
    moving = df["close"].rolling(window, min_periods=window).mean()
    signal = (df["close"] > moving).astype(int).where(moving.notna(), 0)
    position = signal.shift(1).fillna(0)  # critical: next-day effect
    daily = df["adjusted"].pct_change().fillna(0)
    turn = position.diff().abs().fillna(position.abs())
    strategy_daily = (position * daily - turn * trading_cost).clip(lower=-.9999)
    # Start both investments only after SMA becomes available to compare equal periods
    start = window
    strat = (1 + strategy_daily.iloc[start:]).cumprod()
    baseline = (1 + daily.iloc[start:]).cumprod()
    trades = int((turn.iloc[start:] > 0).sum())
    years = len(strat) / 252
    def stats(series: pd.Series) -> dict[str, float]:
        d = series.pct_change().fillna(0)
        peak = series.cummax()
        return {"total_return": float(series.iloc[-1] - 1),
                "cagr": float(series.iloc[-1] ** (1 / years) - 1),
                "max_drawdown": float((series / peak - 1).min()),
                "volatility": float(d.std() * np.sqrt(252))}
    curves = pd.DataFrame({"SMA strategy": strat, "Buy & hold": baseline}).dropna()
    return {"strategy": stats(strat), "buy_hold": stats(baseline),
            "trades": trades, "curve": curves, "cost": trading_cost, "window": window,
            "price_adjusted": price_adjusted,
            "return_basis": "adjusted total return" if price_adjusted else "unadjusted price return",
            "data_warnings": data_warnings}
