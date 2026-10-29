"""Test-only financial statement fixtures; never displayed as real market data."""
from datetime import datetime, timedelta, timezone
from io import StringIO

import numpy as np
import pandas as pd
import pytest

from financials import parse_fundamentals, apply_fundamentals, FUNDAMENTALS_TEMPLATE


def statement(**changes):
    values = {"Country": "United States", "Symbol": "MSFT", "AsOf": datetime.now(timezone.utc).date().isoformat(),
              "Currency": "USD", "Source": "https://issuer.example/annual-report", "profit_margin": ".25",
              "roe": ".3", "debt_eq": "80", "revenue_growth": ".12", "earnings_growth": "",
              "pe": "24", "payout": ".4", "beta": "", "market_cap": ""}
    values.update(changes)
    return values


def file_for(*rows):
    return StringIO(pd.DataFrame(rows).to_csv(index=False))


def test_maps_financial_fields_and_keeps_missing_absent():
    parsed = parse_fundamentals(file_for(statement(Symbol="msft")))
    info = parsed[("United States", "MSFT")]
    assert info["profitMargins"] == .25
    assert info["returnOnEquity"] == .3
    assert info["debtToEquity"] == 80
    assert info["fundamentals_source"] == "User import"
    assert info["fundamentals_reference"].startswith("https://")
    assert "earningsGrowth" not in info and "beta" not in info


def test_country_and_symbol_are_the_composite_key():
    rows = [statement(), statement(Country="United Kingdom", Symbol="MSFT", Currency="GBP")]
    parsed = parse_fundamentals(file_for(*rows))
    assert ("United States", "MSFT") in parsed
    assert ("United Kingdom", "MSFT.L") in parsed


def test_currency_price_units_are_case_sensitive():
    info = parse_fundamentals(file_for(statement(Country="United Kingdom", Symbol="VOD", Currency="GBp")))
    assert info[("United Kingdom", "VOD.L")]["currency"] == "GBp"
    with pytest.raises(ValueError, match="case-sensitive"):
        parse_fundamentals(file_for(statement(Country="United Kingdom", Symbol="VOD", Currency="gbp")))


@pytest.mark.parametrize("age", [-1, 551])
def test_rejects_future_and_stale_statement_dates(age):
    as_of = datetime.now(timezone.utc).date() - timedelta(days=age)
    with pytest.raises(ValueError, match="future|older"):
        parse_fundamentals(file_for(statement(AsOf=as_of.isoformat())))


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "garbage"])
def test_rejects_invalid_financial_values(value):
    with pytest.raises(ValueError, match="finite|number"):
        parse_fundamentals(file_for(statement(profit_margin=value)))


def test_rejects_duplicate_country_symbol():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_fundamentals(file_for(statement(), statement()))


def test_rejects_credential_columns_and_credential_urls_without_retaining_values():
    with pytest.raises(ValueError, match="Unknown fundamentals columns"):
        parse_fundamentals(file_for(statement(ApiToken="not-a-real-token")))
    with pytest.raises(ValueError, match="without embedded credentials"):
        parse_fundamentals(file_for(statement(Source="https://user:pass@issuer.example/report")))


def test_rejects_empty_missing_negative_cap_and_oversize():
    with pytest.raises(ValueError, match="no company rows"):
        parse_fundamentals(StringIO(FUNDAMENTALS_TEMPLATE))
    with pytest.raises(ValueError, match="missing columns"):
        parse_fundamentals(StringIO("Country,Symbol\nUnited States,MSFT\n"))
    with pytest.raises(ValueError, match="cannot be negative"):
        parse_fundamentals(file_for(statement(market_cap="-1")))
    with pytest.raises(ValueError, match="at most"):
        parse_fundamentals(file_for(*[statement() for _ in range(2001)]))


def test_recomputes_metrics_without_mutating_item_or_converting_price_units():
    dates = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=300)
    prices = pd.DataFrame({"Close": 100 + np.arange(300) / 100}, index=dates)
    item = {"symbol": "MSFT", "country": "United States", "prices": prices,
            "info": {"longName": "Test company", "currency": "USD", "price_adjusted": False},
            "metrics": {"price": float(prices["Close"].iloc[-1]), "currency": "USD"}, "news": {"items": []}}
    values = parse_fundamentals(file_for(statement()))[("United States", "MSFT")]
    updated = apply_fundamentals(item, values)
    assert updated["metrics"]["profit_margin"] == .25
    assert updated["metrics"]["price"] == item["metrics"]["price"]
    assert updated["metrics"]["price_adjusted"] is False
    assert updated["prices"] is prices
    assert "profitMargins" not in item["info"]
    with pytest.raises(ValueError, match="currency does not match"):
        apply_fundamentals(item, {**values, "currency": "GBP"})


def test_applies_financials_to_news_only_item_without_inventing_price():
    values = parse_fundamentals(file_for(statement()))[("United States", "MSFT")]
    item = {"prices": pd.DataFrame(), "info": {"currency": "USD"}, "metrics": {"price": None}}
    updated = apply_fundamentals(item, values)
    assert updated["metrics"]["price"] is None
    assert updated["metrics"]["pe"] == 24
