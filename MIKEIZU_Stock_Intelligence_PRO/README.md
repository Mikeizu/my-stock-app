# MIKEIZU Stock Intelligence PRO v2

A private stock-research dashboard with country selection, company discovery and a combined percentage ranking. Research a basket, inspect the evidence behind each score, and review linked news, potential drivers and risks on the same page.

**A research score of 80% means 80/100 on the displayed heuristic. It is not an 80% chance of profit, a predicted return, or an instruction to buy.** The app does not place orders, connect to a broker or guarantee investment results.

## Start the app

Use **Python 3.11, 3.12 or 3.13**. Extract the ZIP to a writable folder before running it. Internet is needed to install dependencies and retrieve external market data and news. Standard public-feed access needs no API key or password.

- **Windows:** Install Python from [python.org](https://www.python.org/downloads/) with “Add Python to PATH” enabled, then double-click `START_WINDOWS.bat`. It creates `.venv`, installs packages and opens the local dashboard. Keep the terminal open; `Ctrl+C` stops the server.
- **macOS / Linux:** Open a terminal in the extracted folder and run `bash run_linux_mac.sh`. Open the loopback address and port 8501 shown in the terminal if a browser does not open automatically.

Both launchers bind to `127.0.0.1`; they do not publish the app on the internet. This is a Python source application, not a signed Windows EXE.

## Discover, compare and investigate

1. Select **Stock market / country** in the sidebar and choose **Balanced**, **Income** or **Growth**.
2. In **Discover & Rank**, search a company name or ticker with **Find stocks**. Choose matching listings and use **Add selected companies to basket**. You can also use the starter basket or enter known exchange tickers manually.
3. Choose up to **24 stocks per batch**, including imported CSV files, and press **Run combined research**. The app gathers price history, available fundamentals and recent company/ticker news, then calculates the seven-factor score.
4. Review **Data coverage**, **Evidence sufficient**, the rating and source dates alongside the score. Stocks with sufficient evidence sort before incomplete observations. Export the complete ranking as CSV when needed.
5. Use **Inspect a ranked stock** to see the factor breakdown, price chart, conditional prospects, risks, verification checklist and source-linked headlines. The same selected stock is available to the dedicated research tools.

Changing strategy recalculates scores from the downloaded evidence. **Refresh prices, search & news** clears the external-data caches; run research again to fetch new observations. Price history is cached for up to 30 minutes; company search and news are cached for up to 15 minutes.

### What the country selector covers

There are **30 listing-market presets**: United States, Nigeria, United Kingdom, Canada, India, South Africa, Germany, France, Australia, Japan, China, Hong Kong, Brazil, Singapore, Switzerland, Netherlands, Italy, Spain, Sweden, Norway, Denmark, Finland, Belgium, Mexico, South Korea, Taiwan, Indonesia, Malaysia, New Zealand and Saudi Arabia.

The filter describes the **listing exchange**, not the issuer's headquarters. A US-listed ADR can therefore appear under United States. Yahoo company/ticker discovery is not a full-text sector screener. Starter lists are examples, not recommendations or complete exchange directories; searches and research batches do not scan every stock or every website.

Bare local tickers receive the primary suffix for the selected market: for example `VOD` becomes `VOD.L` in United Kingdom and `RELIANCE` becomes `RELIANCE.NS` in India. Explicit listings outside the selected market are rejected. Use `.BO` for BSE, `.SZ` for Shenzhen or another supported secondary suffix when appropriate. Stock availability remains subject to provider coverage.

Quotes retain their native units. **GBp means British pence**, while GBP means pounds; **ZAc means South African cents**, while ZAR means rand. Check the displayed currency before planning income. Comparisons are not adjusted for exchange-rate movements, tax, sector or country differences.

## How percentage rankings work

The combined score uses seven groups of observed evidence. The nominal weights sum to 100% for each strategy:

| Factor | Balanced | Income | Growth |
|---|---:|---:|---:|
| Income: observed trailing dividends and earnings payout | 15% | 30% | 5% |
| Quality: profit margin, return on equity and debt/equity | 20% | 20% | 20% |
| Growth: reported revenue and earnings growth | 15% | 5% | 25% |
| Momentum: historical returns and 200-day price trend | 20% | 10% | 25% |
| Valuation: trailing price/earnings | 10% | 10% | 10% |
| Risk: historical annualized volatility and beta | 10% | 15% | 5% |
| News: recent headline-only sentiment | 10% | 10% | 10% |

Each factor receives a score from 0 to 100. Its effective weight is its strategy weight multiplied by the fraction of underlying inputs available. The final percentage is the weighted average over that available evidence. **Data coverage** reports the supported portion of the original total weight, so one populated input cannot make an otherwise missing factor look complete. Missing inputs are never invented.

News uses a bounded sentiment heuristic and financial phrases, not verified full-text analysis. Full news input coverage requires **five distinct, dated, citable HTTPS stories from the past 14 days**. Duplicate titles and duplicate story URLs, including common tracking variations, do not multiply the evidence. Future, undated, stale or uncitable stories do not influence the current news score. A positive headline can still describe an irrelevant or unreliable claim; read the source.

An eligible shortlist entry requires:

- At least **60% weighted input coverage** and **200 daily price observations**.
- A valid positive closing price dated no more than **seven calendar days ago**, with no future date.
- At least **three reported fundamental inputs** among profit margin, ROE, debt/equity, revenue growth, earnings growth and trailing P/E.
- No reported negative debt/equity and no historical annualized volatility above **80%**.

Incomplete or stale records retain partial observations but are labelled **INSUFFICIENT / STALE DATA**. Severe volatility or negative-equity evidence produces **HIGH RISK / REVIEW** when the other data gates pass. Other labels include **RESEARCH CANDIDATE**, **WATCH / COMPARE** and **CAUTION / REVIEW**. Eligibility means sufficient evidence for comparison; it does not mean the investment is suitable or safe.

The methodology also flags unusually high trailing yield, unsustainable earnings payout, losses and other supplied risk indicators. A high trailing yield can follow a collapsing price or a special dividend. Broad financial ratios are not normalized for sector accounting, fiscal period or market conditions. Review issuer filings and comparable companies before relying on them.

When available, provider analyst targets appear as **opinion context**. Individual target dates, assumptions and currency alignment are not independently verified. Analyst opinions, simulated scenarios and historical backtests are **excluded from the research score**.

## News, prospects and research tools

The combined news adapter searches Google News by company and ticker/events, and Yahoo ticker RSS where supported. It merges returned headlines, keeps publication dates and source links, and exposes each query's success or failure under **Source coverage & web-search provenance**. Partial failures stay visible; a failed feed is not replaced by fabricated news.

The prospects panel separates observed strengths, risks and questions to verify. Potential drivers are conditional on future execution and events. It cannot identify every possible prospect or unforeseen risk. Links to issuer-report searches and the market-data source support further investigation.

The selected stock also supports:

- **Historical scenarios:** 1,000 five-day block-bootstrap paths, using up to 756 adjusted daily returns for 1–24 months. P10/P50/P90 are illustrative historical-resampling outcomes, not reliable forecasts or calibrated confidence intervals. At least 252 daily prices are required.
- **Dividend income planning:** Whole shares multiplied by observed trailing 12-month dividends, assuming those payments repeat. Monthly equivalents are budgeting averages, not payment schedules. No future declaration, tax, fee or currency conversion is included.
- **Backtest Lab:** Long-or-cash moving-average strategies use next-session positions, an entry/exit cost and a comparable buy-and-hold period. The combined panel uses 200 days and 0.15% per entry/exit; the dedicated tab offers other settings. Results are in-sample and omit slippage, tax, FX and cash interest.
- **Watchlist:** Local SQLite storage for symbols, notes and an optional review price, plus CSV export. A review price is not an automatic alert.
- **Optional local AI:** Install [Ollama](https://ollama.com/) separately and download a model, for example `ollama pull llama3.2:3b`. The News Intelligence tab can summarize the already-retrieved headline metadata through the local Ollama server. It does not read article bodies, does not alter scores and can produce inaccuracies. Ollama is optional; standard research works without an LLM subscription.

## Nigeria / NGX and licensed CSV data

Nigeria is selectable, but **this package does not supply a live or licensed NGX price feed**. Nigerian symbols are not silently converted into US stocks. Use authorized exchange, broker or other licensed price histories through **Add licensed CSV price histories** in Discover & Rank. Importing CSVs is also available for the other markets.

Use one CSV per stock, with its ticker as the filename, such as `DANGCEM.csv`. Optional company mappings such as `DANGCEM=Dangote Cement` improve news relevance. Choose the currency or price unit actually used in all files in the batch.

Required columns are `Date,Close`; optional columns are `Adj Close,Dividends`. Files are limited to 20,000 rows. For example, the following illustrates the **format only**, not actual market history:

```csv
Date,Close,Adj Close,Dividends
2026-01-02,100.0,98.0,0
2026-01-05,101.0,99.0,0
```

Without adjusted closes, returns and scenarios use unadjusted prices and may omit dividends or include split distortions. Without a Dividends column, cash yield is missing rather than assumed. Price CSVs do not supply company fundamentals, so price-only imports cannot qualify for the eligible shortlist. News availability does not fill missing financial statements. The single-file **CSV / NGX Data** tab remains available for price research.

Obtain data you have permission to use; the [Nigerian Exchange](https://ngxgroup.com/exchange/data/) provides information about authorized data services. Integrating a licensed NGX or commercial global feed requires separate development and appropriate agreements; it is not included here.

## Connectivity, privacy and troubleshooting

Default market data uses [`yfinance`](https://ranaroussi.github.io/yfinance/), unofficial access to Yahoo Finance intended for personal research. It is not an official licensed quote feed. Prices and fundamentals may be delayed, incomplete, stale, rate-limited or blocked. The app displays actual observed price dates and download-check timestamps; those are different from real-time tradable quotes.

Networks running the standard adapters may need these HTTPS destinations:

```text
query1.finance.yahoo.com
query2.finance.yahoo.com
finance.yahoo.com
fc.yahoo.com
guce.yahoo.com
feeds.finance.yahoo.com
news.google.com
```

Package installation also needs PyPI and its package-file hosts. Browser links to original publishers and issuer reports use their own destinations. No feed API credentials are required by the current public adapters; access can still be denied by the network or provider. Do not disable TLS verification to work around connectivity errors.

If a search or stock fails, check the selected listing country, ticker suffix, provider status and displayed error. Clear caches and rerun after an access or configuration change. If port 8501 is occupied, stop the existing server or choose another port in the launcher. A read-only extraction folder or running directly inside a ZIP can prevent installation or local storage.

The watchlist is stored in `data/watchlist.sqlite3`; back it up separately. `data/provider-cache/` contains local Yahoo cache databases and may hold provider session cookies. Keep watchlists, caches, `.venv`, logs and local secrets out of distributable ZIPs. There are no supplied cloud accounts, push notifications, background scheduler, user authentication or broker permissions.

For public or commercial deployment, arrange licensed market-data and news sources and review their redistribution rights. This source package grants no market-data license.

## Developer checks and validation status

From the extracted app folder, use an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app.py dashboard.py engine.py markets.py providers.py research.py storage.py ollama_helper.py
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python` after creating the environment with your installed Python launcher.

Tests cover scoring, missing and stale evidence, country/ticker rules, feed parsing and deduplication, CSV handling and mocked Streamlit workflows. Synthetic test fixtures are not presented as actual market observations.

**Live-feed validation remains blocked in the current development cloud:** tested Yahoo and Google endpoints returned proxy tunnel `403 Forbidden`. Network-domain additions have been saved for environment-settings review; saving a draft does not apply network policy or establish working feeds. Automated provider and application tests use controlled fixtures. No live price, stock recommendation or news connectivity claim is made from those tests.
