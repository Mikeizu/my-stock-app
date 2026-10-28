"""Country discovery, combined research and evidence in one Streamlit workspace."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

from engine import get_metrics, sentiment_from_headlines, bootstrap_returns, backtest_sma
from markets import MARKETS, market_symbols, resolve_symbols, search_companies
from providers import csv_market
from research import evaluate_unified, evidence_brief
from storage import save

MAX_STOCKS = 24


@st.cache_data(ttl=900, max_entries=120, show_spinner=False)
def find_companies(query: str, country: str):
    return search_companies(query, country)


def ranking_frame(items, goal):
    """Rank eligible evidence first; an unsupported high score cannot lead the list."""
    rows = []
    for item in items:
        m = item["metrics"]
        result = evaluate_unified(m, item["news"], info=item.get("info"), goal=goal)
        rows.append({
            "Ticker": item["symbol"], "Company": m["name"],
            "Research score (%)": result["score"], "Data coverage (%)": result["coverage"] * 100,
            "Evidence sufficient": result["eligible"], "Rating": result["label"],
            "Close": m["price"], "Currency": m["currency"],
            "12m return (%)": None if m["ret_12m"] is None else m["ret_12m"] * 100,
            "Dividend yield (%)": None if m["yield_12m"] is None else m["yield_12m"] * 100,
            "Volatility (%)": None if m["volatility"] is None else m["volatility"] * 100,
            "Headlines": item["news"]["count"], "Price date": m["as_of"],
            "Country": item["country"], "Price source": item.get("source", "Yahoo Finance / yfinance"),
            "Fetched at": item["fetched"], "Strategy": goal,
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["Evidence sufficient", "Research score (%)", "Data coverage (%)", "Ticker"],
        ascending=[False, False, False, True], na_position="last",
    ).reset_index(drop=True)


def _import_stock(uploaded, country, company_names, news_fetch, currency=None):
    label = Path(uploaded.name).stem.strip()[:65]
    name = company_names.get(label.upper(), label)
    uploaded.seek(0)
    prices, info, fetched = csv_market(uploaded, name)
    info["currency"] = currency or MARKETS[country]["currency"].split(" / ")[0]
    info["country"] = country
    metrics = get_metrics(prices, info)
    metrics["price_adjusted"] = info.get("price_adjusted", False)
    try:
        bundle = news_fetch(name, label, country)
    except Exception as exc:
        bundle = {"articles": [], "errors": [str(exc)[:240]], "queries": []}
    return {"symbol": label, "prices": prices, "info": info, "fetched": fetched,
            "metrics": metrics, "news": sentiment_from_headlines(bundle["articles"]),
            "news_error": "; ".join(bundle["errors"]), "news_queries": bundle["queries"],
            "country": country, "source": "User-imported CSV (source not independently verified)"}


def _render_brief(item):
    brief = evidence_brief(item["metrics"], item["news"], info=item.get("info"))
    st.subheader("Prospects & risks")
    st.caption("Observed evidence and conditions to investigate. Prospects are conditional; no source covers every future event.")
    bull, bear = st.columns(2)
    with bull:
        with st.container(border=True):
            st.markdown("#### What supports the case")
            for line in brief["strengths"]:
                st.write("• " + line)
    with bear:
        with st.container(border=True):
            st.markdown("#### What could weaken the case")
            for line in brief["risks"]:
                st.write("• " + line)
    with st.expander("What to verify before a buying decision", expanded=True):
        for line in brief["verify"]:
            st.write("• " + line)
        source1, source2 = st.columns(2)
        source1.link_button("Find issuer reports & filings", "https://www.google.com/search?q=" +
                            quote_plus(item["metrics"]["name"] + " investor relations annual report"),
                            use_container_width=True)
        if not item.get("source", "").startswith("User-imported"):
            source2.link_button("Open market-data source", "https://finance.yahoo.com/quote/" +
                                quote_plus(item["symbol"]), use_container_width=True)
    if brief.get("analyst"):
        opinion = brief["analyst"]
        with st.expander("Analyst opinion context — excluded from the score"):
            st.write(f"Provider mean target: **{opinion['currency']} {opinion['target_mean']:,.2f}** · "
                     f"Reported analyst count: **{opinion['analyst_count']}**")
            st.caption(opinion["note"])


def _render_tools(item):
    with st.expander("Return scenarios, dividend income & historical strategy check"):
        st.caption("These tools use the same selected stock. Historical simulations and backtests are excluded from the research score.")
        horizon = st.select_slider("Scenario horizon (months)", options=[1, 3, 6, 12, 24], value=12,
                                   key="combined_horizon")
        try:
            sim = bootstrap_returns(item["prices"], horizon_months=horizon)
            a, b, c = st.columns(3)
            a.metric("P10 historical scenario", f"{sim['p10']:+.1%}")
            b.metric("P50 historical scenario", f"{sim['median']:+.1%}")
            c.metric("P90 historical scenario", f"{sim['p90']:+.1%}")
            st.caption("1,000 five-day block-bootstrap paths. Illustrative return scenarios, not price targets, calibrated probabilities or expected returns. Excludes fees, tax and FX.")
        except ValueError as exc:
            st.info(str(exc))
        m = item["metrics"]
        investment = st.number_input(f"Income-planning amount ({m['currency']})", min_value=0.0,
                                     value=10000.0, step=100.0, key="combined_investment")
        if m["dividend_12m"] is not None:
            shares = int(investment // m["price"])
            st.write(f"**{shares:,} whole shares** · Historical annual dividend run-rate: "
                     f"**{m['currency']} {shares * m['dividend_12m']:,.2f}**")
            st.caption("Assumes the trailing dividend repeats. Future dividends can change; no currency conversion, taxes or fees included.")
        else:
            st.info("Dividend-event history is missing; income is not estimated.")
        try:
            bt = backtest_sma(item["prices"], window=200, trading_cost=.0015)
            a, b, c = st.columns(3)
            a.metric("200-day strategy return", f"{bt['strategy']['total_return']:+.1%}")
            b.metric("Buy-and-hold return", f"{bt['buy_hold']['total_return']:+.1%}")
            c.metric("Strategy max drawdown", f"{bt['strategy']['max_drawdown']:.1%}")
            st.line_chart(bt["curve"], height=220)
            st.caption("Same historical period; next-session signals; 0.15% per entry/exit. In-sample, with no slippage, tax, FX or cash interest. Past results do not validate future performance.")
        except ValueError as exc:
            st.info(str(exc))


def render_discovery(country, goal, fetch, news_fetch, show_assessment, show_headlines):
    market = MARKETS[country]
    st.markdown("### One search. A fuller investment picture.")
    st.write("Choose a market, discover companies, and combine financial quality, growth, valuation, "
             "dividends, price trends, risk and recent news in one ranking.")
    st.caption(f"Selected listing market: {country} · Native currency: {market['currency']} · Strategy: {goal}")

    lookup_key = f"company_matches_{market['code']}"
    basket_key = f"research_basket_{market['code']}"
    seeds = market_symbols(country)
    if market["supported"]:
        with st.form(f"lookup_{market['code']}"):
            query = st.text_input("Find a company or ticker", placeholder="e.g. Microsoft, MSFT",
                                  help="Provider company/ticker search within the selected listing market. Search is not an exhaustive exchange screener.")
            lookup = st.form_submit_button("Find stocks", use_container_width=True)
        if lookup:
            if len(query.strip()) < 2:
                st.session_state[lookup_key] = []
                st.warning("Enter at least two characters to search.")
            else:
                try:
                    with st.spinner("Searching company listings in " + country + "…"):
                        st.session_state[lookup_key] = find_companies(query.strip(), country)
                    if not st.session_state[lookup_key]:
                        st.info("No matching listings returned for this market. Try the exchange ticker or add a known ticker below.")
                except Exception as exc:
                    st.session_state[lookup_key] = []
                    st.error("Company search unavailable: " + str(exc)[:280])
        matches = st.session_state.get(lookup_key, [])
        if matches:
            labels = {x["symbol"]: f"{x['name']} · {x['symbol']} · {x['exchange']}" for x in matches}
            choices = st.multiselect("Matching companies", list(labels), format_func=labels.get,
                                     default=[matches[0]["symbol"]], key=f"hits_{market['code']}")
            if st.button("Add selected companies to basket", disabled=not choices):
                current = st.session_state.get(basket_key, seeds[:6])
                combined = list(dict.fromkeys(current + choices))
                if len(combined) > MAX_STOCKS:
                    st.warning(f"The basket supports {MAX_STOCKS} stocks. Remove some stocks before adding more.")
                else:
                    st.session_state[basket_key] = combined
        options = list(dict.fromkeys(seeds + [x["symbol"] for x in matches] +
                                     st.session_state.get(basket_key, [])))
        if basket_key not in st.session_state:
            st.session_state[basket_key] = seeds[:6]
        selected = st.multiselect("Research basket", options, key=basket_key,
                                  help="Starter lists are examples, not recommendations or a complete list of country stocks.")
        manual = st.text_input("Add more exchange tickers", placeholder="Comma-separated local or provider tickers",
                               key=f"manual_{market['code']}")
        st.caption(f"Up to {MAX_STOCKS} stocks per batch. Starter lists and company-search results do not cover every listed security.")
    else:
        st.info(market["note"])
        selected, manual = [], ""

    with st.expander("Add licensed CSV price histories" + (" — required for this market" if not market["supported"] else " (optional)"),
                     expanded=not market["supported"]):
        uploaded = st.file_uploader("One CSV per stock; name each file with its ticker", type=["csv"],
                                    accept_multiple_files=True, key=f"imports_{market['code']}")
        names_text = st.text_area("Company names for more relevant news (optional)",
                                  placeholder="DANGCEM=Dangote Cement\nMTNN=MTN Nigeria", key=f"names_{market['code']}")
        import_currency = st.text_input("Currency / price unit used in CSV files", value=market["currency"].split(" / ")[0],
                                        key=f"import_currency_{market['code']}", max_chars=12,
                                        help="All imports in this batch use this unit. Use GBp for UK pence or ZAc for South African cents when appropriate.")
        st.caption("Required: Date, Close. Optional: Adj Close, Dividends. CSV history alone cannot supply company fundamentals or a high-confidence recommendation. Currency uses the selected market.")
    names = {}
    for line in names_text.splitlines():
        if "=" in line:
            symbol, company = line.split("=", 1)
            names[symbol.strip().upper()] = company.strip()[:65]

    if st.button("Run combined research", type="primary", use_container_width=True,
                 disabled=not (selected or manual.strip() or uploaded)):
        try:
            symbols = resolve_symbols(",".join(selected + [manual]), country) if selected or manual.strip() else []
            if len(symbols) + len(uploaded) > MAX_STOCKS:
                raise ValueError(f"Choose at most {MAX_STOCKS} stocks including CSV imports.")
            imported_labels = [Path(f.name).stem.strip().upper() for f in uploaded]
            if len(set(imported_labels)) != len(imported_labels) or set(imported_labels).intersection(symbols):
                raise ValueError("Each ticker must appear once. Remove duplicate CSVs or choose CSV or online data for that ticker.")
            if uploaded and not import_currency.strip():
                raise ValueError("Enter the currency or price unit used by your CSV files.")
            collected, errors = [], []
            count = len(symbols) + len(uploaded)
            progress = st.progress(0, text="Gathering prices, fundamentals and independent news sources…")
            with ThreadPoolExecutor(max_workers=3) as pool:
                jobs = {pool.submit(fetch, sym, True, country): sym for sym in symbols}
                for f in uploaded:
                    jobs[pool.submit(_import_stock, f, country, names, news_fetch, import_currency.strip())] = f.name
                for completed, future in enumerate(as_completed(jobs), 1):
                    try:
                        collected.append(future.result())
                    except Exception as exc:
                        errors.append(f"{jobs[future]}: {str(exc)[:280]}")
                    progress.progress(completed / count, text=f"Reviewed {completed} of {count} stocks")
            st.session_state["combined_scan"] = {
                "country": country, "items": collected, "errors": errors,
                "checked": datetime.now(timezone.utc).isoformat(timespec="seconds"), "requested": count,
                "run_id": datetime.now(timezone.utc).isoformat(),
            }
        except ValueError as exc:
            st.error(str(exc))

    scan = st.session_state.get("combined_scan")
    if not scan or scan["country"] != country:
        with st.container(border=True):
            st.markdown("#### Your research starts here")
            st.write("Select a country and stocks, then run combined research. Rankings, supporting evidence, "
                     "source-linked news and historical tools will appear together here.")
            st.caption("Research score: evidence alignment from 0–100%. It is not the probability of profit or a predicted return.")
        return

    for error in scan["errors"]:
        st.error(error)
    if not scan["items"]:
        st.warning("No usable price history was returned. No prices, news or ratings have been invented. "
                   "Check provider access, exchange tickers or import authorized CSV histories.")
        return

    frame = ranking_frame(scan["items"], goal)
    eligible = frame[frame["Evidence sufficient"]]
    st.divider()
    a, b, c, d = st.columns(4)
    a.metric("Stocks reviewed", f"{len(frame)} / {scan['requested']}")
    b.metric("Sufficient evidence", len(eligible))
    c.metric("Headlines assessed", int(frame["Headlines"].sum()))
    d.metric("Highest eligible score", "Unavailable" if eligible.empty else f"{eligible.iloc[0]['Research score (%)']:.1f}%")
    if eligible.empty:
        st.info("No stock has enough fresh evidence for a candidate rating. Partial scores below remain research observations.")
    else:
        top = eligible.iloc[0]
        st.write(f"**Highest-ranked eligible stock in this basket: {top['Ticker']} · {top['Company']}** — {top['Rating']}")
    st.caption(f"Results checked: {scan['checked']}. Weights recalculate immediately when strategy changes. "
               "Ranking compares this basket only; evidence sufficiency is not a buy recommendation.")
    only_eligible = st.toggle("Show only stocks with sufficient evidence", value=False)
    display = frame[frame["Evidence sufficient"]] if only_eligible else frame
    st.dataframe(display, hide_index=True, use_container_width=True, column_config={
        "Research score (%)": st.column_config.ProgressColumn("Research score", format="%.1f%%", min_value=0, max_value=100),
        "Data coverage (%)": st.column_config.ProgressColumn("Data coverage", format="%.0f%%", min_value=0, max_value=100),
        "Close": st.column_config.NumberColumn(format="%.2f"),
        "12m return (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Dividend yield (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Volatility (%)": st.column_config.NumberColumn(format="%.2f%%"),
    })
    st.download_button("Download complete research ranking", frame.to_csv(index=False),
                       f"MIKEIZU_{market['code']}_{goal}_research.csv", "text/csv")
    st.caption("Percentages are evidence scores or explicitly named historical measures. No score is a win probability. "
               "Valuation and accounting ratios are broad heuristics and may not be comparable across sectors.")

    by_symbol = {x["symbol"]: x for x in scan["items"]}
    chosen = st.selectbox("Inspect a ranked stock", frame["Ticker"].tolist(),
                          format_func=lambda s: f"{s} · {by_symbol[s]['metrics']['name']}")
    item = by_symbol[chosen]
    selection = (country, chosen, scan.get("run_id", scan["checked"]))
    if st.session_state.get("last_combined_selection") != selection:
        st.session_state["research"] = item
        st.session_state["last_combined_selection"] = selection
    with st.container(border=True):
        show_assessment(item, goal)
        chart = item["prices"]
        column = "Adj Close" if "Adj Close" in chart else "Close"
        adjusted = column == "Adj Close" and item.get("info", {}).get("price_adjusted", True)
        st.line_chart(chart[[column]].rename(columns={column: "Historical adjusted close" if adjusted else "Historical close (unadjusted)"}), height=260)
        st.caption("Native price units. UK quotes may use GBp (pence); check the quote currency above. Adjusted prices reflect provider adjustments where supplied.")
        if not adjusted:
            st.warning("No adjusted closing series was supplied. Returns and scenarios use unadjusted prices and may omit dividends or include split distortions.")
        if st.button("Save selected stock to watchlist", key="save_combined"):
            try:
                save(item["symbol"])
                st.success("Saved to your local watchlist.")
            except ValueError as exc:
                st.error(str(exc))
    _render_brief(item)
    _render_tools(item)
    show_headlines(item["news"])
    with st.expander("Source coverage & web-search provenance"):
        st.write("Price source: " + item.get("source", "Yahoo Finance / yfinance"))
        st.write("Price date: " + item["metrics"]["as_of"] + " · Download checked: " + item["fetched"])
        for query in item.get("news_queries", []):
            st.write(query)
        if item.get("news_error"):
            st.warning(item["news_error"])
        st.caption("News analysis covers returned, dated headlines, not full article text or an exhaustive web crawl. "
                   "Open sources and issuer filings to verify claims; news is not a complete view of future prospects.")
