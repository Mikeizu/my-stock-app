"""Deterministic research tests; fixtures are synthetic, never market quotes."""
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from research import WEIGHTS, evaluate_unified, evidence_brief


def fixture():
    now = datetime.now(timezone.utc)
    metrics = {
        "price": 100., "as_of": now.date().isoformat(), "observations": 650,
        "yield_12m": .04, "payout": .5, "profit_margin": .2, "roe": .25,
        "debt_eq": 50., "revenue_growth": .15, "ret_6m": .2,
        "ret_12m": .3, "sma200": 90., "pe": 18., "volatility": .25,
        "currency": "USD",
    }
    info = {"earningsGrowth": .2, "beta": 1., "currency": "USD"}
    news = {"average": .5, "count": 5, "items": [
        {"title": f"Synthetic dated headline {i}", "sentiment": .5,
         "published": (now - timedelta(days=1, minutes=i)).isoformat(),
         "link": f"https://example.com/{i}", "source": "Test fixture"}
        for i in range(5)
    ]}
    return metrics, news, info


def test_complete_input_measures_full_coverage_and_percentage_bounds():
    m, news, info = fixture()
    result = evaluate_unified(m, news, info)
    assert result["coverage"] == 1.
    assert result["eligible"]
    assert result["label"] == "RESEARCH CANDIDATE"
    assert 0 <= result["score"] <= 100
    assert all(value == 1 for value in result["input_coverage"].values())
    assert sum(result["weights"].values()) == 100


def test_partial_factor_does_not_receive_full_coverage():
    m, news, info = fixture()
    del m["roe"]
    del m["debt_eq"]
    result = evaluate_unified(m, news, info)
    assert result["parts"]["quality"] is not None
    assert result["input_coverage"]["quality"] == pytest.approx(1 / 3)
    assert result["coverage"] == pytest.approx(1 - .20 * 2 / 3)


def test_available_partial_inputs_receive_only_supported_weight():
    m, news, info = fixture()
    del info["earningsGrowth"]
    del info["beta"]
    result = evaluate_unified(m, news, info)
    assert result["coverage"] == pytest.approx(1 - .15 / 2 - .10 / 2)
    effective = {k: v * result["input_coverage"][k] for k, v in result["weights"].items()}
    expected = sum(result["parts"][k] * v for k, v in effective.items()) / sum(effective.values())
    assert result["score"] == pytest.approx(expected)


def test_missing_everything_is_unscored_and_ineligible():
    result = evaluate_unified({}, {"average": 1, "count": 999})
    assert result["score"] is None
    assert result["coverage"] == 0
    assert not result["eligible"]
    assert result["label"] == "INSUFFICIENT / STALE DATA"


@pytest.mark.parametrize("offset", [-8, 1])
def test_stale_and_future_prices_cannot_be_ranked(offset):
    m, news, info = fixture()
    m["as_of"] = (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()
    result = evaluate_unified(m, news, info)
    assert not result["eligible"]
    assert result["label"] == "INSUFFICIENT / STALE DATA"


@pytest.mark.parametrize("date", [None, "Unknown", "2026-99-99"])
def test_invalid_date_is_a_blocker(date):
    m, news, info = fixture()
    m["as_of"] = date
    assert not evaluate_unified(m, news, info)["eligible"]


def test_short_history_and_price_only_csv_cannot_be_top_candidates():
    m, news, info = fixture()
    m["observations"] = 199
    assert not evaluate_unified(m, news, info)["eligible"]
    for key in ("profit_margin", "roe", "debt_eq", "revenue_growth", "pe"):
        m.pop(key, None)
    m["observations"] = 650
    result = evaluate_unified(m, news)
    assert not result["eligible"]
    assert any("fundamentals" in x for x in result["warnings"])


def test_stale_future_undated_and_duplicate_news_do_not_inflate_coverage():
    m, news, info = fixture()
    now = datetime.now(timezone.utc)
    news["items"] = [news["items"][0], news["items"][0],
        {"title": "Old", "sentiment": 1, "published": (now - timedelta(days=15)).isoformat()},
        {"title": "Future", "sentiment": 1, "published": (now + timedelta(days=1)).isoformat()},
        {"title": "Unknown date", "sentiment": 1, "published": "Unknown"}]
    result = evaluate_unified(m, news, info)
    assert result["recent_headline_count"] == 1
    assert result["input_coverage"]["news"] == .2
    assert result["parts"]["news"] == pytest.approx(72.5)


def test_severe_volatility_is_flagged_even_with_positive_other_inputs():
    m, news, info = fixture()
    m["volatility"] = 1.2
    result = evaluate_unified(m, news, info)
    assert not result["eligible"]
    assert result["label"] == "HIGH RISK / REVIEW"
    assert any("volatility" in text for text in result["warnings"])


def test_negative_equity_is_not_rewarded_as_low_leverage():
    m, news, info = fixture()
    good = evaluate_unified(m, news, info)
    m["debt_eq"] = -50
    bad = evaluate_unified(m, news, info)
    assert bad["parts"]["quality"] < good["parts"]["quality"]
    assert bad["label"] == "HIGH RISK / REVIEW"
    assert not bad["eligible"]
    assert any("negative" in text for text in bad["warnings"])


def test_income_high_yield_and_unsustainable_payout_warn_and_prevent_candidate():
    m, news, info = fixture()
    m["yield_12m"], m["payout"] = .15, 1.4
    result = evaluate_unified(m, news, info, goal="Income")
    assert result["parts"]["income"] <= 30
    assert result["label"] != "RESEARCH CANDIDATE"
    assert any("payout" in text for text in result["warnings"])


def test_nonpayer_is_known_zero_income_not_missing_income():
    m, news, info = fixture()
    m["yield_12m"], m["payout"] = 0, None
    result = evaluate_unified(m, news, info, goal="Income")
    assert result["parts"]["income"] == 0
    assert result["input_coverage"]["income"] == 1
    assert result["label"] != "RESEARCH CANDIDATE"


def test_non_finite_numeric_inputs_are_omitted():
    m, news, info = fixture()
    m.update(pe=float("nan"), profit_margin=float("inf"), roe="bad")
    info["beta"] = float("nan")
    result = evaluate_unified(m, news, info)
    assert result["parts"]["valuation"] is None
    assert math.isfinite(result["score"])
    assert result["coverage"] < 1


def test_strategy_weights_change_and_invalid_goals_default():
    m, news, info = fixture()
    outcomes = {goal: evaluate_unified(m, news, info, goal) for goal in WEIGHTS}
    assert all(sum(r["weights"].values()) == 100 for r in outcomes.values())
    assert len({r["score"] for r in outcomes.values()}) == 3
    assert evaluate_unified(m, news, info, "unknown")["goal"] == "Balanced"


def test_analyst_opinions_are_context_only_and_do_not_move_score():
    m, news, info = fixture()
    original = evaluate_unified(m, news, info)
    info.update(targetMeanPrice=1000, numberOfAnalystOpinions=12)
    assert evaluate_unified(m, news, info)["score"] == original["score"]
    brief = evidence_brief(m, news, info)
    assert brief["analyst"]["difference"] == 9
    assert "not a forecast" in brief["analyst"]["note"]
    assert len(brief["news_evidence"]) == 5
    assert all(x["link"].startswith("https://") for x in brief["news_evidence"])
    assert any("Provider analyst opinion" in text for text in brief["verify"])


def test_missing_evidence_never_creates_bull_case_or_analyst_target():
    brief = evidence_brief({}, None, {"targetMeanPrice": 500})
    assert brief["analyst"] is None
    assert "does not establish" in brief["strengths"][0]
    assert brief["risks"]
    assert brief["verify"]


def test_syndicated_headlines_and_tracking_link_variants_count_once():
    m, news, info = fixture()
    base = news["items"][0]
    news["items"] = [
        {**base, "title": "Synthetic issuer beats earnings - Test publisher", "source": "Test publisher"},
        {**base, "title": "Synthetic issuer beats earnings!", "link": "https://other.example.com/story"},
        {**base, "title": "Different headline for same article", "link": base["link"] + "?utm_source=rss#tracking"},
    ]
    result = evaluate_unified(m, news, info)
    assert result["recent_headline_count"] == 1
    assert result["input_coverage"]["news"] == .2


def test_news_without_citable_source_links_is_not_scored():
    m, news, info = fixture()
    news["items"] = [{**item, "link": ""} for item in news["items"]]
    result = evaluate_unified(m, news, info)
    assert result["parts"]["news"] is None
    assert result["input_coverage"]["news"] == 0


def test_price_only_csv_without_dividend_column_cannot_fill_income_or_qualify():
    from io import StringIO
    import numpy as np
    import pandas as pd
    from engine import get_metrics
    from providers import csv_market

    dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=650)
    close = 100 * np.exp(np.arange(650) * .001)
    csv = pd.DataFrame({"Date": dates, "Close": close}).to_csv(index=False)
    prices, info, fetched = csv_market(StringIO(csv), "Synthetic price-only CSV")
    metrics = get_metrics(prices, info)
    result = evaluate_unified(metrics, None, info)
    assert metrics["yield_12m"] is None
    assert result["parts"]["income"] is None
    assert result["input_coverage"]["income"] == 0
    assert result["coverage"] < .6
    assert result["label"] == "INSUFFICIENT / STALE DATA"
    assert not result["eligible"]


def test_fractional_analyst_count_is_not_a_valid_consensus():
    m, news, info = fixture()
    info.update(targetMeanPrice=120, numberOfAnalystOpinions=.5)
    assert evidence_brief(m, news, info)["analyst"] is None
