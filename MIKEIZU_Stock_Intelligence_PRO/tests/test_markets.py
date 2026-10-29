import pytest

from markets import MARKETS, belongs_to_market, market_symbols, resolve_symbols, search_companies


def test_country_seed_lists_use_the_selected_listing_market():
    assert len(MARKETS) >= 20
    for country, config in MARKETS.items():
        assert all(belongs_to_market(symbol, country) for symbol in config["seeds"]), country


def test_symbols_apply_country_suffix_and_deduplicate():
    assert resolve_symbols("vod, VOD.L; HSBA\nAZN.L", "United Kingdom") == ["VOD.L", "HSBA.L", "AZN.L"]
    assert resolve_symbols("INFY, 500209.BO", "India") == ["INFY.NS", "500209.BO"]
    assert resolve_symbols("MSFT,brk-b, MSFT", "United States") == ["MSFT", "BRK-B"]
    assert resolve_symbols("700,700.HK, 0005.HK", "Hong Kong") == ["0700.HK", "0005.HK"]


@pytest.mark.parametrize("text,country", [("VOD.L", "United States"), ("MSFT.NS", "United Kingdom"),
                                          ("SAP.DE", "France"), ("AAA.INVALID", "United States")])
def test_symbols_never_silently_change_a_foreign_listing(text, country):
    with pytest.raises(ValueError):
        resolve_symbols(text, country)


def test_nigeria_directory_never_resolves_to_an_unrelated_us_stock(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Nigeria directory discovery must work locally without a Yahoo request")
    monkeypatch.setattr("markets.requests.get", unexpected)
    assert market_symbols("Nigeria")
    assert all(symbol.endswith(".NGX") for symbol in market_symbols("Nigeria"))
    assert resolve_symbols("", "Nigeria") == []
    assert resolve_symbols("DANGCEM,GTCO", "Nigeria") == ["DANGCEM.NGX", "GTCO.NGX"]
    assert search_companies("Guaranty", "Nigeria")[0]["symbol"] == "GTCO.NGX"
    with pytest.raises(ValueError):
        resolve_symbols("MSFT", "Nigeria")


def test_seed_lists_are_not_mutated_by_callers():
    symbols = market_symbols("United States")
    symbols.clear()
    assert market_symbols("United States")


def test_search_is_equity_only_and_filters_listing_not_issuer_domicile(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"quotes": [
                {"symbol": "SHEL", "quoteType": "EQUITY", "exchange": "NYQ", "longname": "Shell US ADR"},
                {"symbol": "SHEL.L", "quoteType": "EQUITY", "exchange": "LSE", "longname": "Shell plc"},
                {"symbol": "SHEL.L", "quoteType": "EQUITY", "exchange": "LSE", "longname": "Duplicate"},
                {"symbol": "SHEL-OPTION", "quoteType": "OPTION", "exchange": "LSE"},
                {"symbol": "SHEL", "quoteType": "EQUITY", "exchange": "LSE", "longname": "Bad suffix"},
                {"symbol": "BAD; COMMAND", "quoteType": "EQUITY", "exchange": "LSE"},
            ]}
    calls = []
    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr("markets.requests.get", fake_get)
    assert search_companies("Shell", "United Kingdom") == [
        {"symbol": "SHEL.L", "name": "Shell plc", "exchange": "LSE", "country": "United Kingdom"}]
    assert calls[0][1]["params"]["newsCount"] == 0
    assert calls[0][1]["timeout"] == (5, 12)


def test_discovery_errors_are_visible_not_replaced_with_seed_hits(monkeypatch):
    import requests
    def denied(*args, **kwargs):
        raise requests.HTTPError("403 blocked")
    monkeypatch.setattr("markets.requests.get", denied)
    with pytest.raises(requests.HTTPError):
        search_companies("Microsoft", "United States")


def test_short_company_queries_do_not_make_network_requests(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("No network request should be made")
    monkeypatch.setattr("markets.requests.get", unexpected)
    with pytest.raises(ValueError, match="two characters"):
        search_companies("a", "United States")
