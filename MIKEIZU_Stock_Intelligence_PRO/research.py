"""Transparent, evidence-weighted stock research; scores are never win probabilities.

Only supplied observations are scored. Missing sub-inputs reduce their factor's
effective weight, rather than making a partly populated factor look complete.
Analyst targets are displayed as dated/undated opinions, never used as facts
about future prices or as inputs to the ranking.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from engine import clip, safe_float


WEIGHTS = {
    "Balanced": {"income": 15, "quality": 20, "growth": 15, "momentum": 20,
                 "valuation": 10, "risk": 10, "news": 10},
    "Income": {"income": 30, "quality": 20, "growth": 5, "momentum": 10,
               "valuation": 10, "risk": 15, "news": 10},
    "Growth": {"income": 5, "quality": 20, "growth": 25, "momentum": 25,
               "valuation": 10, "risk": 5, "news": 10},
}

METHODOLOGY = (
    "Seven-factor heuristic: trailing dividend income, profitability and leverage, "
    "reported growth, historical momentum, trailing P/E valuation, historical risk, "
    "and recent headline tone. Each factor is weighted by the fraction of its "
    "underlying inputs actually available. News reaches full input coverage at "
    "five distinct, dated headlines in the past 14 days. Factors are reweighted "
    "over available evidence; coverage is reported separately. A score of 80% "
    "means 80/100 on this formula, not an 80% chance of profit. Sector, country, "
    "tax and currency differences are not normalized; compare peers and check "
    "issuer filings. Analyst targets, simulations and in-sample backtests are "
    "context, not extra independent prediction signals."
)


def _mean(values: list[float | None]) -> tuple[float | None, float]:
    present = [v for v in values if v is not None]
    return (sum(present) / len(present), len(present) / len(values)) if present else (None, 0.0)


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _recent_news(news: dict | None, now: datetime) -> list[dict]:
    items, seen_titles, seen_links = [], set(), set()
    for item in (news or {}).get("items", []):
        title = str(item.get("title") or "").strip()
        key = html.unescape(title)
        publisher = str(item.get("source") or "").strip()
        if publisher and key.casefold().endswith(" - " + publisher.casefold()):
            key = key[:-(len(publisher) + 3)]
        title_key = re.sub(r"[^\w]+", " ", key.casefold()).strip()
        try:
            link = urlsplit(str(item.get("link") or ""))
            if link.scheme != "https" or not link.hostname or link.username or link.password:
                continue
            query = sorted((k, v) for k, v in parse_qsl(link.query)
                           if not k.casefold().startswith("utm_"))
            link_key = urlunsplit((link.scheme, link.netloc.casefold(), link.path,
                                   urlencode(query), ""))
        except ValueError:
            continue
        timestamp = _time(item.get("published"))
        sentiment = safe_float(item.get("sentiment"))
        if (not title_key or title_key in seen_titles or link_key in seen_links or timestamp is None
                or timestamp > now or timestamp < now - timedelta(days=14)
                or sentiment is None):
            continue
        seen_titles.add(title_key)
        seen_links.add(link_key)
        items.append({**item, "sentiment": max(-1, min(1, sentiment))})
    return items


def evaluate_unified(metrics: dict[str, Any], news: dict[str, Any] | None,
                     info: dict[str, Any] | None = None,
                     goal: str = "Balanced") -> dict[str, Any]:
    """Rate observed evidence, with explicit incompleteness and eligibility gates.

    ``eligible`` means the stock has enough current evidence to participate in
    the ranked shortlist; it is not a recommendation to purchase the stock.
    Scores remain visible for incomplete research, but those rows must not be
    presented as the best buy. All numeric inputs are checked for finiteness.
    """
    info = info or {}
    now = datetime.now(timezone.utc)
    goal = goal if goal in WEIGHTS else "Balanced"
    weights = dict(WEIGHTS[goal])
    m = {k: safe_float(v) for k, v in metrics.items()}
    parts: dict[str, float | None] = {}
    coverage: dict[str, float] = {}

    y, payout = m.get("yield_12m"), m.get("payout")
    if y is not None and y < 0:
        y = None
    yield_score = None if y is None else clip(y * 1600)
    if y is not None and y > .09:
        yield_score = min(yield_score, 30)
    payout_score = (None if payout is None else
                    85 if .2 <= payout <= .75 else
                    0 if payout < 0 or payout > 1 else 50)
    if y == 0:
        # Confirmed non-payers need no payout ratio to establish zero income.
        parts["income"], coverage["income"] = 0.0, 1.0
    elif y is None:
        # Payout ratio alone does not establish any cash income.
        parts["income"], coverage["income"] = None, 0.0
    elif payout_score is None:
        parts["income"], coverage["income"] = yield_score, .7
    else:
        parts["income"], coverage["income"] = .7 * yield_score + .3 * payout_score, 1.0

    margin, roe, debt = (m.get(k) for k in ("profit_margin", "roe", "debt_eq"))
    # Yahoo debt/equity is in percentage points; a negative value indicates
    # negative equity and is never interpreted as unusually low leverage.
    parts["quality"], coverage["quality"] = _mean([
        None if margin is None else clip(40 + margin * 170),
        None if roe is None else (0 if debt is not None and debt < 0 else clip(35 + roe * 150)),
        None if debt is None else (0 if debt < 0 else clip(100 - max(0, debt - 50) * .33)),
    ])
    revenue = m.get("revenue_growth")
    earnings = safe_float(info.get("earningsGrowth"))
    if earnings is None:
        earnings = safe_float(info.get("earningsQuarterlyGrowth"))
    parts["growth"], coverage["growth"] = _mean([
        None if revenue is None else clip(50 + revenue * 170),
        None if earnings is None else clip(50 + earnings * 120),
    ])

    r6, r12, sma, price = (m.get(k) for k in ("ret_6m", "ret_12m", "sma200", "price"))
    parts["momentum"], coverage["momentum"] = _mean([
        None if r6 is None else clip(50 + r6 * 110),
        None if r12 is None else clip(50 + r12 * 65),
        None if sma is None or sma <= 0 or price is None or price <= 0 else (75 if price >= sma else 25),
    ])
    pe = m.get("pe")
    parts["valuation"] = None if pe is None else (0 if pe <= 0 else clip(100 - (pe - 12) * 2.1))
    coverage["valuation"] = 0.0 if pe is None else 1.0
    volatility = m.get("volatility")
    if volatility is not None and volatility < 0:
        volatility = None
    beta = safe_float(info.get("beta"))
    parts["risk"], coverage["risk"] = _mean([
        None if volatility is None else clip(100 - volatility * 125),
        None if beta is None else clip(100 - abs(beta) * 30),
    ])
    recent = _recent_news(news, now)
    parts["news"] = clip(50 + 45 * sum(x["sentiment"] for x in recent) / len(recent)) if recent else None
    coverage["news"] = min(1.0, len(recent) / 5)

    effective = {k: weights[k] * coverage[k] for k in weights}
    total = sum(effective.values())
    score = sum((parts[k] or 0) * effective[k] for k in weights) / total if total else None
    supported = total / 100
    warnings: list[str] = []
    blockers: list[str] = []

    observed = m.get("observations") or 0
    if observed < 200:
        blockers.append("Limited price history: fewer than 200 daily observations")
    timestamp = _time(metrics.get("as_of"))
    if timestamp is None:
        blockers.append("Price timestamp missing or invalid")
    elif timestamp.date() > now.date():
        blockers.append("Price date is in the future")
    elif (now.date() - timestamp.date()).days > 7:
        blockers.append("Stale market prices: latest observation is more than seven calendar days old")
    if price is None or price <= 0:
        blockers.append("No valid positive closing price")
    if supported < .6:
        blockers.append("Insufficient input coverage: less than 60% of strategy weight")
    fundamental_count = sum(v is not None for v in (margin, roe, debt, revenue, earnings, pe))
    if fundamental_count < 3:
        blockers.append("Insufficient fundamentals: fewer than three reported quality, growth or valuation inputs")

    if y is not None and y > .09:
        warnings.append("Trailing dividend yield exceeds 9%; check for a price collapse, special dividend or unsustainable payout")
    if payout is not None and (payout > 1 or payout < 0):
        warnings.append("Dividend payout is outside 0–100% of earnings; check cash cover and exceptional items")
    if debt is not None and debt < 0:
        warnings.append("Reported debt/equity is negative; investigate negative book equity")
    if pe is not None and pe <= 0:
        warnings.append("Trailing P/E is non-positive; it does not establish a cheap profitable company")
    if margin is not None and margin < 0:
        warnings.append("Reported profit margin is negative")
    if revenue is not None and revenue < 0:
        warnings.append("Reported revenue growth is negative")
    if volatility is not None and volatility > .6:
        warnings.append("High historical volatility: annualized variability exceeds 60%")
    if len(recent) < 5:
        warnings.append(f"Limited recent news sample: {len(recent)} dated headlines; headline tone cannot verify full articles")
    if goal == "Income" and (y is None or y <= 0):
        warnings.append("No observed positive trailing dividend yield for the Income strategy")

    severe_risk = ((volatility is not None and volatility > .8)
                   or (debt is not None and debt < 0))
    eligible = not blockers and not severe_risk
    if blockers:
        label = "INSUFFICIENT / STALE DATA"
    elif severe_risk:
        label = "HIGH RISK / REVIEW"
    elif (score is not None and score >= 72
          and not (goal == "Income" and (y is None or y <= 0 or (payout is not None and (payout < 0 or payout > 1))))
          and not (margin is not None and margin < 0)):
        label = "RESEARCH CANDIDATE"
    elif score is not None and score >= 55:
        label = "WATCH / COMPARE"
    else:
        label = "CAUTION / REVIEW"
    return {"score": score, "coverage": supported, "eligible": eligible,
            "label": label, "parts": parts, "weights": weights,
            "input_coverage": coverage, "warnings": blockers + warnings,
            "goal": goal, "methodology": METHODOLOGY,
            "recent_headline_count": len(recent)}


def evidence_brief(metrics: dict[str, Any], news: dict[str, Any] | None,
                   info: dict[str, Any] | None = None) -> dict[str, Any]:
    """A compact factual bull/bear checklist with explicitly conditional prospects."""
    info = info or {}
    strengths, risks, verify = [], [], []
    m = {k: safe_float(v) for k, v in metrics.items()}
    margin, growth, debt, payout, y = (m.get(k) for k in
                                      ("profit_margin", "revenue_growth", "debt_eq", "payout", "yield_12m"))
    if margin is not None:
        (strengths if margin > 0 else risks).append(f"Reported profit margin: {margin:.1%}. Future profits depend on sustaining sales and costs.")
    if growth is not None:
        (strengths if growth > 0 else risks).append(f"Reported revenue growth: {growth:+.1%}. Further growth is a possible driver only if demand and execution hold up.")
    if debt is not None:
        if debt < 0:
            risks.append("Negative reported debt/equity may reflect negative equity; inspect the balance sheet.")
        elif debt > 150:
            risks.append(f"Debt/equity is {debt:.0f}%; refinancing cost and cash generation deserve attention.")
        else:
            verify.append(f"Reported debt/equity is {debt:.0f}%; compare with sector peers and debt maturities.")
    pe = m.get("pe")
    if pe is not None:
        if pe <= 0:
            risks.append("Non-positive trailing P/E: investigate losses or data anomalies rather than assuming undervaluation.")
        else:
            verify.append(f"Trailing P/E is {pe:.1f}×. Compare normalized earnings and peers; a low multiple alone does not establish value.")
    if y is not None and y > 0:
        (risks if y > .09 else strengths).append(f"Observed trailing dividend yield: {y:.2%}; future distributions require issuer declarations.")
    if payout is not None and (payout > 1 or payout < 0):
        risks.append(f"Reported dividend payout: {payout:.0%} of earnings. Check free cash flow, special payments and dividend cover.")
    price, sma = m.get("price"), m.get("sma200")
    if price is not None and sma is not None and sma > 0:
        above = price >= sma
        (strengths if above else risks).append(f"Latest observed close is {'above' if above else 'below'} the 200-day average; trends can reverse.")
    vol = m.get("volatility")
    if vol is not None:
        (risks if vol > .45 else verify).append(f"Historical annualized volatility: {vol:.1%}; this is variability, not a maximum future loss.")

    recent = _recent_news(news, datetime.now(timezone.utc))
    news_evidence = []
    for item in recent:
        link = str(item.get("link") or "")
        if not link.startswith("https://"):
            continue
        tone = "Positive" if item["sentiment"] > .15 else "Negative" if item["sentiment"] < -.15 else "Mixed"
        news_evidence.append({"title": item["title"], "link": link,
                              "source": item.get("source", "News source"),
                              "published": item["published"], "tone": tone})
    if not recent:
        risks.append("No recent dated headline evidence is available; event risks may be missing.")

    # Provider consensus is an opinion, not independently verified upside.
    target = safe_float(info.get("targetMeanPrice"))
    analysts = safe_float(info.get("numberOfAnalystOpinions"))
    analyst = None
    if target is not None and target > 0 and price is not None and price > 0 and analysts is not None and analysts >= 1:
        analyst = {"target_mean": target, "analyst_count": int(analysts),
                   "difference": target / price - 1,
                   "currency": str(info.get("currency") or metrics.get("currency") or "Unknown"),
                   "note": "Provider analyst consensus; individual target dates and currency alignment are not verified. This is an opinion, not a forecast or ranking input."}
        verify.append(
            f"Provider analyst opinion: mean target {analyst['currency']} {target:,.2f} "
            f"from {int(analysts)} reported opinions, {target / price - 1:+.1%} relative "
            "to the observed close. Target dates and currency alignment are unverified; "
            "this is not a forecast or a scoring input. Check original broker research."
        )

    verify.extend([
        "Confirm latest earnings, guidance, free cash flow, dilution and debt maturities in issuer filings.",
        "Check upcoming earnings/dividend dates and exchange announcements; headlines are not full-text evidence.",
        "Compare sector peers and consider valuation, liquidity, taxes, fees, local rules and currency exposure before buying.",
    ])
    if not strengths:
        strengths.append("Available evidence does not establish a specific positive investment case.")
    return {"strengths": strengths, "risks": risks, "verify": verify,
            "news_evidence": news_evidence[:6], "analyst": analyst}
