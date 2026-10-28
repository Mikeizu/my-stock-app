"""Country-specific listing universes and public company discovery.

Seed lists are starting points, not complete exchange listings or recommendations.
The country filter refers to the exchange listing, not an issuer's domicile.
"""
from __future__ import annotations

import re
import requests

from engine import normalize_symbol


def _market(code, currency, exchanges, suffixes, seeds, note=""):
    return {"code": code, "currency": currency, "exchanges": tuple(exchanges),
            "suffixes": tuple(suffixes), "seeds": tuple(seeds.split()),
            "news_region": code,
            # Google does not provide an English edition for every country.
            # Preserve country as gl, using a real English edition as fallback.
            "news_edition": f"{code}:en" if code in {"US", "GB", "CA", "IN", "AU", "ZA", "NZ", "SG"} else "US:en",
            "supported": True, "note": note}


MARKETS = {
    "United States": _market("US", "USD", ("NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS"), ("",),
        "MSFT AAPL GOOGL AMZN NVDA JPM JNJ KO PG XOM V PEP"),
    "Nigeria": {"code": "NG", "currency": "NGN", "exchanges": (), "suffixes": (),
        "seeds": (), "news_region": "NG", "news_edition": "NG:en", "supported": False,
        "note": "Nigeria / NGX requires authorized CSV history or a licensed market-data feed. "
                "Yahoo coverage is not supplied; Nigerian symbols will never be converted into US stocks."},
    "United Kingdom": _market("GB", "GBP / GBp", ("LSE",), (".L",),
        "AZN.L SHEL.L HSBA.L ULVR.L BP.L REL.L GSK.L LSEG.L NG.L VOD.L"),
    "Canada": _market("CA", "CAD", ("TOR", "VAN", "CNQ", "NEO"), (".TO", ".V", ".CN", ".NE"),
        "RY.TO TD.TO SHOP.TO ENB.TO CNR.TO CP.TO BNS.TO FTS.TO"),
    "India": _market("IN", "INR", ("NSI", "BSE"), (".NS", ".BO"),
        "RELIANCE.NS TCS.NS HDFCBANK.NS INFY.NS ICICIBANK.NS ITC.NS BHARTIARTL.NS LT.NS",
        "Bare symbols use NSE (.NS). Enter .BO explicitly for BSE listings."),
    "South Africa": _market("ZA", "ZAR / ZAc", ("JNB",), (".JO",),
        "NPN.JO FSR.JO SBK.JO MTN.JO SOL.JO VOD.JO AGL.JO SLM.JO"),
    "Germany": _market("DE", "EUR", ("GER", "FRA", "STU", "BER", "DUS", "HAM", "HAN", "MUN"),
        (".DE", ".F", ".SG", ".BE", ".DU", ".HM", ".HA", ".MU"),
        "SAP.DE SIE.DE ALV.DE DTE.DE BMW.DE BAS.DE MBG.DE IFX.DE"),
    "France": _market("FR", "EUR", ("PAR",), (".PA",),
        "MC.PA OR.PA TTE.PA SAN.PA AIR.PA SU.PA BNP.PA AI.PA"),
    "Australia": _market("AU", "AUD", ("ASX",), (".AX",),
        "CBA.AX BHP.AX CSL.AX NAB.AX WBC.AX ANZ.AX WES.AX RIO.AX"),
    "Japan": _market("JP", "JPY", ("JPX",), (".T",),
        "7203.T 6758.T 8306.T 9984.T 6501.T 6861.T 8058.T 9432.T"),
    "China": _market("CN", "CNY", ("SHH", "SHZ"), (".SS", ".SZ"),
        "600519.SS 601398.SS 601318.SS 600036.SS 000858.SZ 300750.SZ",
        "Bare symbols use Shanghai (.SS). Enter .SZ explicitly for Shenzhen listings."),
    "Hong Kong": _market("HK", "HKD", ("HKG",), (".HK",),
        "0700.HK 9988.HK 0005.HK 1299.HK 0941.HK 3690.HK 0388.HK 9618.HK"),
    "Brazil": _market("BR", "BRL", ("SAO",), (".SA",),
        "PETR4.SA VALE3.SA ITUB4.SA BBDC4.SA WEGE3.SA ABEV3.SA BBAS3.SA"),
    "Singapore": _market("SG", "SGD", ("SES",), (".SI",),
        "D05.SI O39.SI U11.SI Z74.SI C6L.SI C38U.SI"),
    "Switzerland": _market("CH", "CHF", ("SWX", "VTX"), (".SW",),
        "NESN.SW NOVN.SW ROG.SW UBSG.SW ZURN.SW ABBN.SW"),
    "Netherlands": _market("NL", "EUR", ("AMS",), (".AS",),
        "ASML.AS ADYEN.AS INGA.AS HEIA.AS PHIA.AS WKL.AS"),
    "Italy": _market("IT", "EUR", ("MIL",), (".MI",),
        "ENEL.MI ENI.MI ISP.MI UCG.MI RACE.MI G.MI LDO.MI"),
    "Spain": _market("ES", "EUR", ("MCE",), (".MC",),
        "SAN.MC BBVA.MC IBE.MC ITX.MC TEF.MC REP.MC"),
    "Sweden": _market("SE", "SEK", ("STO",), (".ST",),
        "VOLV-B.ST ATCO-A.ST INVE-B.ST ERIC-B.ST ABB.ST SEB-A.ST"),
    "Norway": _market("NO", "NOK", ("OSL",), (".OL",),
        "EQNR.OL DNB.OL TEL.OL MOWI.OL AKRBP.OL NHY.OL"),
    "Denmark": _market("DK", "DKK", ("CPH",), (".CO",),
        "NOVO-B.CO DSV.CO VWS.CO CARL-B.CO MAERSK-B.CO"),
    "Finland": _market("FI", "EUR", ("HEL",), (".HE",),
        "NOKIA.HE KNEBV.HE SAMPO.HE NESTE.HE FORTUM.HE"),
    "Belgium": _market("BE", "EUR", ("BRU",), (".BR",),
        "ABI.BR KBC.BR UCB.BR ACKB.BR SOLB.BR"),
    "Mexico": _market("MX", "MXN", ("MEX",), (".MX",),
        "WALMEX.MX AMXB.MX FEMSAUBD.MX GFNORTEO.MX CEMEXCPO.MX"),
    "South Korea": _market("KR", "KRW", ("KSC", "KOQ"), (".KS", ".KQ"),
        "005930.KS 000660.KS 005380.KS 035420.KS 051910.KS 035720.KS"),
    "Taiwan": _market("TW", "TWD", ("TAI", "TWO"), (".TW", ".TWO"),
        "2330.TW 2317.TW 2454.TW 2308.TW 2881.TW 2412.TW"),
    "Indonesia": _market("ID", "IDR", ("JKT",), (".JK",),
        "BBCA.JK BBRI.JK BMRI.JK TLKM.JK ASII.JK UNVR.JK"),
    "Malaysia": _market("MY", "MYR", ("KLS",), (".KL",),
        "1155.KL 1295.KL 1023.KL 5347.KL 5819.KL 5183.KL"),
    "New Zealand": _market("NZ", "NZD", ("NZE",), (".NZ",),
        "FPH.NZ AIR.NZ SPK.NZ MEL.NZ CEN.NZ ATM.NZ"),
    "Saudi Arabia": _market("SA", "SAR", ("SAU",), (".SR",),
        "2222.SR 1180.SR 1120.SR 2010.SR 7010.SR 1211.SR"),
}

_KNOWN_SUFFIXES = tuple(sorted({s for m in MARKETS.values() for s in m["suffixes"] if s}, key=len, reverse=True))


def market_symbols(country: str) -> list[str]:
    """Return an independent copy of a non-exhaustive starting list."""
    return list(MARKETS[country]["seeds"])


def belongs_to_market(symbol: str, country: str) -> bool:
    market = MARKETS[country]
    if not market["supported"]:
        return False
    suffix = next((s for s in _KNOWN_SUFFIXES if symbol.endswith(s)), None)
    if country == "United States":
        return suffix is None and "." not in symbol
    return suffix in market["suffixes"]


def resolve_symbols(text: str, country: str) -> list[str]:
    """Validate tickers, apply a selected listing's primary suffix, deduplicate.

    Explicit foreign exchange suffixes are rejected rather than silently changed.
    Company names belong in company discovery, not in this symbol field.
    """
    market = MARKETS[country]
    entries = [s.strip() for s in re.split(r"[,;\s]+", text or "") if s.strip()]
    if entries and not market["supported"]:
        raise ValueError(market["note"])
    symbols = []
    for value in entries:
        symbol = normalize_symbol(value)
        suffix = next((s for s in _KNOWN_SUFFIXES if symbol.endswith(s)), None)
        if suffix and suffix not in market["suffixes"]:
            raise ValueError(f"{symbol} is listed outside {country}. Choose the matching country or remove it.")
        if not suffix:
            if "." in symbol:
                raise ValueError(f"Unknown exchange suffix on {symbol}. Use a ticker from {country}'s exchange.")
            if country == "Hong Kong" and symbol.isdecimal():
                symbol = symbol.zfill(4)
            symbol += market["suffixes"][0]
        elif country == "Hong Kong" and symbol[:-3].isdecimal():
            symbol = symbol[:-3].zfill(4) + ".HK"
        symbol = normalize_symbol(symbol)
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def search_companies(query: str, country: str, limit: int = 10) -> list[dict]:
    """Discover actual equity listings, filtered by the selected exchange country."""
    market = MARKETS[country]
    if not market["supported"]:
        raise ValueError(market["note"])
    query = str(query or "").strip()
    if len(query) < 2:
        raise ValueError("Enter at least two characters of a company name or ticker.")
    if len(query) > 100:
        raise ValueError("Keep company searches under 100 characters.")
    limit = max(1, min(int(limit), 20))
    response = requests.get("https://query1.finance.yahoo.com/v1/finance/search",
        params={"q": query, "quotesCount": 40, "newsCount": 0, "enableFuzzyQuery": "false"},
        headers={"User-Agent": "Mozilla/5.0 MIKEIZU Stock Research/2.0"}, timeout=(5, 12))
    response.raise_for_status()
    rows = response.json().get("quotes", [])
    result, seen = [], set()
    for row in rows:
        if row.get("quoteType") != "EQUITY" or row.get("exchange") not in market["exchanges"]:
            continue
        try:
            symbol = normalize_symbol(row.get("symbol", ""))
        except ValueError:
            continue
        if symbol in seen or not belongs_to_market(symbol, country):
            continue
        seen.add(symbol)
        result.append({"symbol": symbol, "name": str(row.get("longname") or row.get("shortname") or symbol),
                       "exchange": str(row.get("exchDisp") or row.get("exchange")), "country": country})
        if len(result) >= limit:
            break
    return result
