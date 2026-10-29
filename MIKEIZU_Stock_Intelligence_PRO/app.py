"""MIKEIZU Stock Intelligence PRO — personal investment research, not a broker."""
from __future__ import annotations
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from engine import (
    normalize_symbol, get_metrics, sentiment_from_headlines,
    bootstrap_returns, backtest_sma, safe_float,
)
from providers import load_market, load_news_bundle, csv_market
from markets import MARKETS, market_symbols, resolve_symbols
from research import evaluate_unified
from workflow import fetch_research
from exports import safe_csv
from dashboard import render_discovery, find_companies
from storage import save, remove, all_items
from ollama_helper import summarize_locally

st.set_page_config(page_title="MIKEIZU Stock Intelligence PRO", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown("""
<style>
[data-testid="stAppViewContainer"] {background: #071323; color: #eaf1fb;}
[data-testid="stSidebar"] {background: #0b1d32;}
h1, h2, h3 {letter-spacing: -.025em;}
.block-container {padding-top: 1.1rem; max-width: 1450px;}
[data-testid="stMetric"] {background:#10233a; border:1px solid #243b54; padding:14px 16px; border-radius:14px;}
[data-testid="stMetricLabel"] {color:#a5c2d9;}
.stButton>button[kind="primary"] {background: #18b69d; color: #061625; font-weight: 700; border: 0;}
.stTabs [data-baseweb="tab"] {font-weight:650;}
a {color:#5be4d6 !important;}
.mark {border:1px solid #29516c; border-radius:14px; background:linear-gradient(105deg,#103451,#0b203b); padding:21px 25px;}
.mark .eyebrow {font-size:.73rem; letter-spacing:.21em; color:#5ce8d3; font-weight:750;}
.mark h1 {font-size:2rem; margin:6px 0 8px; color:#f8fcff;}
.mark p {margin:0; color:#bfd4e6;}
.note {font-size:.84rem; color:#aabfd5;}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=1800, max_entries=70, show_spinner=False)
def get_market_cached(symbol: str):
    return load_market(symbol)


@st.cache_data(ttl=900, max_entries=100, show_spinner=False)
def get_news_cached(company: str, symbol: str, country: str = "United States"):
    return load_news_bundle(company, symbol, days=14, limit=18, country=country)


def fmt_pct(v, digits=1):
    return "N/A" if v is None else f"{v * 100:+.{digits}f}%"


def fmt_rate(v, digits=2):
    return "N/A" if v is None else f"{v * 100:.{digits}f}%"


def fmt_num(v, digits=2):
    return "N/A" if v is None else f"{v:,.{digits}f}"


def fetch(symbol: str, with_news: bool = True, country: str = "United States", financials=None):
    news_fetch = get_news_cached if with_news else lambda *args: {"articles": [], "errors": [], "queries": []}
    return fetch_research(symbol, country, get_market_cached, news_fetch, financials=financials)


def panel_metrics(m):
    a, b, c, d = st.columns(4)
    a.metric("Last observed close", f"{m['currency']} {fmt_num(m['price'])}", help="End-of-day / provider latest close, not a tradable real-time quote.")
    b.metric("Trailing dividend yield", fmt_rate(m["yield_12m"]), help="Cash dividends observed in the trailing year divided by the last unadjusted close; not a promised forward yield.")
    c.metric("12-month total return" if m.get("price_adjusted", True) else "12-month price return", fmt_pct(m["ret_12m"]), help="Total return uses adjusted closing prices when supplied; otherwise this is unadjusted price change.")
    d.metric("Annualized volatility", fmt_rate(m["volatility"]), help="Historical variability, not a future loss limit.")


def show_headlines(news, header=True):
    if header: st.subheader("Latest headlines & headline-only sentiment")
    if not news["items"]:
        st.info("No headlines returned from the news feed. News sentiment is omitted from the score rather than guessed.")
        return
    for i, item in enumerate(news["items"][:12], 1):
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.markdown(f"**{i}. {item['title']}**")
                st.caption(f"{item['source']} · {item['published']} · Headline signal: {item['tone']} ({item['sentiment']:+.2f})")
            with right:
                st.link_button("Read source", item["link"], use_container_width=True)


def show_assessment(research, goal):
    m = research["metrics"]
    result = evaluate_unified(m, research["news"], info=research.get("info"), goal=goal)
    s = result["score"]
    st.markdown(f"### {research['symbol']} · {m['name']}")
    st.caption(f"Sector: {m['sector']} · Price date: {m['as_of']} · Download checked: {research['fetched']} · Source: {research.get('source', 'User-imported CSV')}")
    panel_metrics(m)
    st.write(f"**Research classification: {result['label']}**  · Research score: **{s:.1f}%**" if s is not None else "**Not enough information to score**")
    st.progress(int(s or 0))
    st.caption(f"Data coverage: {result['coverage']:.0%} of the underlying weighted inputs. Research percentage measures evidence alignment; it is not a probability of profit or an expected return.")
    if result["warnings"]:
        for w in result["warnings"]: st.warning(w)
    if research.get("news_error"):
        st.caption("News access problem: " + research["news_error"][:240])
    parts = pd.DataFrame([
        {"Factor": k.title(), "Score (%)": result['parts'][k],
         "Weight": f"{v}%", "Input coverage": f"{result['input_coverage'][k]:.0%}"}
        for k,v in result["weights"].items()
    ])
    with st.expander("See how the ranking was calculated", expanded=False):
        st.dataframe(parts, hide_index=True, use_container_width=True,
                     column_config={"Score (%)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%")})
        st.caption(result["methodology"])
    return result


with st.sidebar:
    st.markdown("### <span style='color:#5ce8d3'>MIKEIZU</span> / INTELLIGENCE", unsafe_allow_html=True)
    st.caption("GLOBAL EQUITY RESEARCH")
    countries = st.multiselect("Countries to research", list(MARKETS), default=["Nigeria", "United States"], max_selections=8,
                               help="Research up to eight listing markets together. Country means listing exchange, not company headquarters.")
    country = st.selectbox("Country for individual tools", countries or list(MARKETS),
                           help="Sets the country for single-stock input and imports. The main basket researches all selected countries.")
    goal = st.selectbox("Investment strategy", ["Balanced", "Income", "Growth"],
                        help="Adjusts the seven research-factor weights. No strategy guarantees a return.")
    st.divider()
    st.markdown("**Seven lenses. One research score.**")
    st.caption("Financial quality · Growth · Valuation · Income · Price momentum · Risk · News")
    if MARKETS[country]["note"]:
        st.info(MARKETS[country]["note"])
    st.caption("Prices retain their quote currency. Cross-country returns are not adjusted for exchange-rate changes.")
    if st.button("Refresh prices, search & news", use_container_width=True):
        get_market_cached.clear()
        get_news_cached.clear()
        find_companies.clear()
        st.success("External-data cache cleared. Run research again to fetch new observations.")
    st.divider()
    st.caption("Private research · No broker connection · No orders placed")

st.markdown("""
<div class="mark">
<div class="eyebrow">GLOBAL MARKETS · CONNECTED RESEARCH</div>
<h1>MIKEIZU STOCK INTELLIGENCE <span style="color:#5ce8d3">PRO v3</span></h1>
<p>Multi-country deep research · Buy / Sell indicators · Plain-language briefs · Monthly & annual returns</p>
</div>
""", unsafe_allow_html=True)
st.caption("Personal investment research · Percentage scores summarize observed evidence, not profit probabilities. Prices may be delayed; check source timestamps.")

tabs = st.tabs(["🌍 Discover & Rank", "📊 Deep Research", "📰 News Intelligence", "💰 Dividend Planner",
                "🧪 Backtest Lab", "⭐ Watchlist", "📁 CSV / NGX Data", "⚙️ Setup & AI"])

with tabs[0]:
    render_discovery(countries, goal, fetch, get_news_cached, show_assessment, show_headlines)

with tabs[1]:
    st.subheader("Company research & return scenarios")
    symbol = st.text_input("Stock ticker to research", value=(market_symbols(country) or [""])[0], key="deep_symbol_" + MARKETS[country]["code"])
    if st.button("Analyse stock", type="primary", key="deep_fetch", disabled=not MARKETS[country]["supported"]):
        try:
            with st.spinner("Downloading market history and reading recent headlines..."):
                st.session_state["research"] = fetch(symbol, True, country)
        except Exception as exc:
            st.error("Analysis could not complete: " + str(exc))
    if "research" in st.session_state and st.session_state["research"].get("country") in countries and st.session_state["research"]["metrics"]["price"] is not None:
        item = st.session_state["research"]
        m, prices = item["metrics"], item["prices"]
        show_assessment(item, goal)
        p1,p2 = st.columns([2,1])
        with p1:
            st.subheader("Historical adjusted performance")
            adj = prices[["Adj Close"]].dropna() if m.get("price_adjusted") and "Adj Close" in prices else prices[["Close"]].dropna()
            st.line_chart(adj.rename(columns={adj.columns[0]: "Dividend-adjusted price" if m.get("price_adjusted", True) else "Unadjusted closing price"}), height=300)
            st.caption("Price series may reflect split and cash-dividend adjustments; it is not a tradeable current quote.")
            if not m.get("price_adjusted", True):
                st.warning("Adjusted closing prices were not supplied. Returns, backtests and scenarios may omit dividends or include split distortions.")
        with p2:
            st.subheader("Fundamentals")
            st.write(f"**P/E:** {fmt_num(m['pe'])}  \n**Earnings payout ratio:** {fmt_rate(m['payout'])}  \n**Profit margin:** {fmt_rate(m['profit_margin'])}  \n**Return on equity:** {fmt_rate(m['roe'])}  \n**Revenue growth:** {fmt_rate(m['revenue_growth'])}  \n**RSI (14):** {fmt_num(m['rsi'])}  \n**50-day mean:** {fmt_num(m['sma50'])}  \n**200-day mean:** {fmt_num(m['sma200'])}")
        st.subheader("Simulated return scenarios — NOT a price guarantee")
        horizon = st.select_slider("Investment horizon", options=[1,3,6,12,24], value=12,
                                   format_func=lambda v: f"{v} month{'s' if v>1 else ''}")
        try:
            age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(m["as_of"]).date()).days
            if not 0 <= age <= 7:
                raise ValueError("Fresh price history within seven days is required for future scenarios. Historical results remain available.")
            simulation = bootstrap_returns(prices, horizon_months=horizon)
            lo, mid, hi = st.columns(3)
            lo.metric("Pessimistic historical-resampling scenario (10th percentile)", fmt_pct(simulation["p10"]))
            mid.metric("Middle simulated scenario (50th percentile)", fmt_pct(simulation["median"]))
            hi.metric("Optimistic historical-resampling scenario (90th percentile)", fmt_pct(simulation["p90"]))
            st.caption(f"Method: {simulation['method']}; {simulation['samples']:,} paths, future horizon {horizon} months. The method assumes historical return blocks may recur. These percentile bands are not calibrated confidence intervals or reliable predictions. No fees, taxes or FX effects included.")
        except ValueError as exc:
            st.info(str(exc))
        if st.button("Add this stock to watchlist", key="from_research"):
            save(item["symbol"], country=item["country"])
            st.success("Added to your local watchlist.")
    else:
        st.info("Select a ranked stock in Discover & Rank, or enter a market ticker here. For Nigeria, use CSV histories in Discover & Rank.")

with tabs[2]:
    st.subheader("Financial news intelligence")
    st.write("The app retrieves recent headlines, links you to their sources, scores headline tone, and optionally summarizes them using a locally running AI model.")
    if "research" in st.session_state and st.session_state["research"].get("country") in countries:
        item = st.session_state["research"]
        news = item["news"]
        sc = news["average"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Analysed stock", item["symbol"])
        c2.metric("Headlines assessed", news["count"])
        c3.metric("Average headline tone", "Not available" if sc is None else f"{sc:+.2f} / 1")
        show_headlines(news)
        with st.expander("Ask local AI to interpret these headlines (optional)"):
            model = st.text_input("Installed Ollama model", value="llama3.2:3b")
            st.caption("Requires Ollama installed, running locally and the selected model already downloaded. This feature sends only headlines to your local Ollama server. LLM output can be wrong; source links remain authoritative.")
            if st.button("Create local-AI investment brief"):
                try:
                    with st.spinner("Generating a local summary..."):
                        output = summarize_locally(item["symbol"], news["items"], model)
                    st.write(output)
                except Exception as exc:
                    st.error("The local model is unavailable: " + str(exc)[:300])
    else:
        st.info("Run combined research or analyse a ticker to access its news.")

with tabs[3]:
    st.subheader("Dividend income planner")
    st.write("Estimate cash distributions if the *past trailing annual payment per share* were repeated. Future dividends can change or stop.")
    if "research" in st.session_state and st.session_state["research"].get("country") in countries and st.session_state["research"]["metrics"]["price"] is not None:
        item = st.session_state["research"]
        m = item["metrics"]
        if m["dividend_12m"] is None:
            st.warning("No reliable dividend-event dataset for this stock. Income cannot be estimated.")
        else:
            initial = st.number_input(f"Investment amount ({m['currency']})", min_value=0.0, value=10000.0, step=100.0)
            shares = int(initial // m["price"]) if m["price"] else 0
            income = shares * m["dividend_12m"]
            a,b,c,d = st.columns(4)
            a.metric("Estimated whole shares", f"{shares:,}")
            b.metric("Annual cash dividend (historical run-rate)", f"{m['currency']} {income:,.2f}")
            c.metric("Monthly average equivalent", f"{m['currency']} {income/12:,.2f}")
            d.metric("Trailing dividend / share", f"{m['currency']} {fmt_num(m['dividend_12m'])}")
            st.caption("Monthly equivalent is a budgeting average, NOT a monthly payment schedule. Assumes unchanged dividend, shares and price; excludes taxes, fees, foreign exchange and withholding tax.")
            if m["dividend_12m"] == 0:
                st.info("No cash dividend recorded over the trailing year. This is not currently an income-producing candidate based on the available observations.")
    else:
        st.info("Select a stock in Discover & Rank or Deep Research before using the planner.")

with tabs[4]:
    st.subheader("Historical backtest — 200/100/50 day moving average")
    st.write("Compares a long-or-cash trend strategy with buy-and-hold. A signal observed at today's close becomes active the *next* trading session; transaction costs are deducted.")
    if "research" in st.session_state and st.session_state["research"].get("country") in countries and st.session_state["research"]["metrics"]["price"] is not None:
        window = st.select_slider("Moving-average days", options=[50,100,200], value=200)
        fee = st.slider("Cost per position entry/exit (%)", min_value=0.0, max_value=1.0, step=0.05, value=0.15) / 100
        try:
            result = backtest_sma(st.session_state["research"]["prices"], window=window, trading_cost=fee)
            a,b,c,d = st.columns(4)
            a.metric("Strategy cumulative return", fmt_pct(result["strategy"]["total_return"]))
            b.metric("Buy-and-hold return", fmt_pct(result["buy_hold"]["total_return"]))
            c.metric("Strategy max drawdown", fmt_pct(result["strategy"]["max_drawdown"]))
            d.metric("Entry/exit transactions", f"{result['trades']}")
            st.line_chart(result["curve"], height=310, y_label="Growth of 1 unit")
            st.caption("Research-only backtest. Adjusted prices represent dividend/split effects where provided. Ignores cash interest, slippage, taxes, FX, real-time execution, liquidity and survivorship bias. The result is in-sample and is not a forecast. Trade direction: long or cash only.")
        except ValueError as exc:
            st.info(str(exc))
    else:
        st.info("Select a stock in Discover & Rank or Deep Research to enable backtests.")

with tabs[5]:
    st.subheader("Private local watchlist")
    existing = all_items()
    if existing.empty:
        st.info("Your watchlist is empty. Add symbols from this page or Deep Research.")
    else:
        st.dataframe(existing, hide_index=True, use_container_width=True)
        st.download_button("Export watchlist", safe_csv(existing), "mikeizu_watchlist.csv", "text/csv")
    with st.form("watchlist_edit"):
        watch_country = st.selectbox("Watchlist country", list(MARKETS), index=list(MARKETS).index(country))
        symbol_to_save = st.text_input("Ticker", value="")
        thesis = st.text_area("Why are you watching it?", height=80)
        target = st.number_input("Optional review price (0 means none)", min_value=0.0, step=1.0, value=0.0)
        submitted = st.form_submit_button("Save / update ticker", type="primary")
    if submitted:
        try:
            symbols = resolve_symbols(symbol_to_save, watch_country)
            if len(symbols) != 1:
                raise ValueError("Enter exactly one ticker.")
            save(symbols[0], thesis, None if target == 0 else target, country=watch_country)
            st.success("Saved in your computer's SQLite watchlist. Refresh this tab to see it.")
        except Exception as exc: st.error(str(exc))
    if not existing.empty:
        removing = st.selectbox("Remove ticker", list(zip(existing["country"], existing["symbol"])), format_func=lambda entry: entry[0] + " · " + entry[1])
        if st.button("Remove selected ticker"):
            remove(removing[1], country=removing[0])
            st.success("Removed. Refresh this tab to see the updated watchlist.")
    st.caption("Storage: data/watchlist.sqlite3. No cloud syncing, email alerting or broker permissions are enabled.")

with tabs[6]:
    st.subheader("Bring your own licensed market data — including Nigerian equities")
    st.write("If a market is unsupported by the standard provider, upload an end-of-day CSV supplied by your exchange, broker, or other authorized source. You remain responsible for the data rights.")
    file = st.file_uploader("Upload a price CSV", type=["csv"])
    custom_name = st.text_input("Company / ticker label", value="Local market share")
    custom_currency = st.text_input("Currency code", value=MARKETS[country]["currency"].split(" / ")[0], key="csv_currency_" + MARKETS[country]["code"])
    st.code("Date,Close,Adj Close,Dividends\n2026-01-02,100.0,98.0,0\n2026-01-05,101.0,99.0,0", language="csv")
    st.caption("CSV shown is a *format example only*, not real stock-market history. Date & Close are required. Adj Close is needed for correct dividend-adjusted total returns; Dividends is needed for cash-yield estimates. If either is missing, some calculations may not be reliable.")
    if file is not None and st.button("Analyse imported CSV", type="primary"):
        try:
            prices, info, fetched = csv_market(file, custom_name)
            info["currency"] = custom_currency.strip().upper()[:10] or "Unknown"
            prices.attrs["price_adjusted"] = info.get("price_adjusted", False)
            m = get_metrics(prices, info)
            news = sentiment_from_headlines([])
            custom_result = {"symbol": "CSV", "prices": prices, "info": info, "fetched": fetched,
                             "metrics": m, "news": news, "source": "User-imported CSV", "country": country}
            st.session_state["csv_research"] = custom_result
        except Exception as exc:
            st.error(str(exc))
    if "csv_research" in st.session_state and st.session_state["csv_research"].get("country") == country:
        show_assessment(st.session_state["csv_research"], goal)
        st.line_chart(st.session_state["csv_research"]["prices"]["Close"], height=250)
        st.warning("Imported CSV may omit dividend adjustments or fundamental data. Missing values are not evidence of financial strength. Data source and accuracy are your responsibility.")

with tabs[7]:
    st.subheader("Setup, methodology & responsible use")
    st.markdown("""
**Included now:** Select several countries together from 30 listing markets, a 36-company Nigerian directory, company search, a combined research basket,
Buy / holder-only Sell / Not good to buy / Wait for data indicators, calendar-based monthly and annual returns,
seven-factor percentage rankings, input-level data coverage, source-linked Google/Yahoo RSS news,
conditional prospects and risks, fundamentals, price history,
scenario modelling, dividend planner, historical strategy testing, CSV imports and persistent watchlists.

**Optional local AI:** Install [Ollama](https://ollama.com/), download `llama3.2:3b`, then use the News Intelligence tab.
Without Ollama, rule-based headline analysis works. This is not a guaranteed-profit machine.

**Market data provider:** `yfinance` is unofficial and intended for personal research. Its sources may change,
and vendor terms may restrict reuse. All quotes should be verified with the relevant stock exchange/broker.
For public or commercial deployment, use licensed market-data and news feeds.

**Nigeria/NGX:** Browse the built-in company directory, research regional news, import authorized daily
CSV history and dated financial statements, and optionally retain NGX data locally. The .NGX suffix is an
internal app identifier; no Yahoo NGX or live licensed feed is supplied. Missing evidence gets WAIT FOR DATA.

**No auto trading:** The application never connects to a broker, buys shares, executes orders, or guarantees returns.
""")
    st.info("Suggested diligence: confirm cash flows and dividend cover, debt structure, valuation, declared dividend schedules, tax treatment, currency risk and whether the stock suits your financial situation. Do not rely on a score alone.")

st.divider()
st.caption("MIKEIZU Stock Intelligence PRO · Private research build · © 2026 · Last interface refresh: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
