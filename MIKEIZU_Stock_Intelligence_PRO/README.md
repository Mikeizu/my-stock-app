# MIKEIZU Stock Intelligence PRO v3

A private research dashboard for comparing stocks across several countries, including a built-in Nigerian-company directory. It combines seven groups of evidence into a percentage research score, gives a short explanation and a **BUY**, **SELL**, **NOT GOOD TO BUY** or **WAIT FOR DATA** indicator, and separates past returns from future scenarios.

**A research score of 80% means 80/100 on the displayed rules. It is not an 80% chance of profit or a predicted return.** Indicators are deterministic screening rules, not a statistically validated prediction model. The app does not submit orders, connect to a broker, or guarantee profits.

## Start the app

Use **Python 3.11, 3.12 or 3.13**. Extract the ZIP into a writable folder before running it. Internet is needed for the first package installation and for external market data and news. The standard public adapters need no API key or password.

- **Windows:** Install Python from [python.org](https://www.python.org/downloads/) with “Add Python to PATH” enabled, then double-click `START_WINDOWS.bat`. It creates `.venv`, installs dependencies and opens the local dashboard. Keep the terminal open; `Ctrl+C` stops it.
- **macOS / Linux:** In the extracted app folder, run `bash run_linux_mac.sh`. If a browser does not open automatically, use the loopback address and port 8501 printed by Streamlit.

Both launchers bind to `127.0.0.1`; they do not publish the app on the internet. This is Python source, not a signed Windows EXE.

## Research Nigeria and other countries together

1. In **Countries to research**, select up to **eight listing markets**. Nigeria and United States are selected initially. **Country for individual tools** controls the single-stock tools; it does not limit the main basket to one country.
2. In each country section, search for companies, select matching results and add them to that country's basket. You can also keep the starter examples or enter additional exchange tickers.
3. Optionally import daily price CSVs and dated company fundamentals. A CSV for a ticker takes precedence over an online request for that ticker in the same batch.
4. Select at most **48 stocks in total**, then choose **Run multi-country deep research**.
5. Review the **Indicator**, **Brief analysis**, **Data coverage**, currency, source and price date together. Use **Inspect a researched stock** for the plain-language buying case, risks, return analysis, source-linked news and detailed rules.
6. To assess shares you already own, enable **Review this basket as stocks I already own**. Only that mode can produce a SELL indicator. Without it, weak buying evidence produces NOT GOOD TO BUY.

Changing strategy or holding mode recalculates the displayed decision from already-downloaded evidence. **Refresh prices, search & news** clears external-data caches; run research again after refreshing. Price data is cached for up to 30 minutes; company discovery and news for up to 15 minutes. Retained NGX histories must be updated by importing new authorized observations; clearing a cache does not create new NGX data.

The CSV ranking export includes each stock's country and currency. The stock-brief JSON export includes its decision, metrics, performance analysis and source-query information. Values in different currencies are not added together.

### Markets and ticker identities

There are **30 listing-market presets**: United States, Nigeria, United Kingdom, Canada, India, South Africa, Germany, France, Australia, Japan, China, Hong Kong, Brazil, Singapore, Switzerland, Netherlands, Italy, Spain, Sweden, Norway, Denmark, Finland, Belgium, Mexico, South Korea, Taiwan, Indonesia, Malaysia, New Zealand and Saudi Arabia.

Country means **listing exchange**, not issuer headquarters. A US-listed ADR can appear under United States. Starter baskets are examples, not recommendations or complete exchange directories. Yahoo company/ticker discovery is not a full-text sector screener, and the app does not scan every listing or every website.

Bare local tickers receive the selected market's primary suffix, for example `VOD` → `VOD.L` in United Kingdom and `RELIANCE` → `RELIANCE.NS` in India. Use `.BO` for a BSE listing or `.SZ` for Shenzhen when appropriate. Explicit listings outside the chosen market are rejected. Nigeria uses an internal `.NGX` namespace described below. Stock identities and watchlist entries include both country and ticker so a similar symbol in another market does not overwrite an entry.

Prices retain their native units. **GBp means British pence**, while GBP means pounds; **ZAc means South African cents**, while ZAR means rand. No currency conversion, tax or country/sector normalization is applied. Check the quote unit before interpreting a gain/loss amount.

## Nigerian stocks and authorized data

The app includes a **36-company NGX research directory** with names and sectors, including banks, cement producers, telecommunications companies and other issuers. Search locally by company, ticker or sector even if quote access is unavailable. The directory is a starting list, not a complete or continuously verified record of current listings; confirm listing status and announcements with the [Nigerian Exchange](https://ngxgroup.com/exchange/data/equities-price-list/).

`GTCO.NGX`, `DANGCEM.NGX` and similar identifiers belong to this app. **`.NGX` is not a Yahoo Finance suffix.** Nigerian requests are never silently converted into unrelated US stocks.

**No automatic live or licensed NGX price feed is bundled.** Without authorized daily history, the app can still assemble company metadata and returned regional news, but it shows WAIT FOR DATA for the trading indicator and withholds returns. It does not invent quotes, fundamentals or news. To enable Nigerian price research:

1. Obtain daily history you may use from an exchange, broker or authorized provider.
2. Import one CSV per ticker in the Nigeria section, named for example `GTCO.csv` or `GTCO.NGX.csv`.
3. Use **NGN** as the price unit. Add dated financial inputs if you want a sufficiently supported fundamental assessment.
4. Optionally enable **Remember NGX imports on this computer**. This saves the authorized history and whitelisted financial metadata under `data/ngx/` for later scans.

Remembered data stays local and keeps its original observation dates; it does not become live or independently verified. Import an updated history and financial statement when required. `data/ngx/` may contain private/licensed information and must not be included in a distributable ZIP. Integrating a commercial NGX feed requires separate provider access, licensing and implementation; none is implied by the directory.

## Price and financial imports

### Daily price CSVs

Required columns: `Date,Close`. Optional columns: `Adj Close,Dividends`. Files are limited to 20,000 rows. Use one positive daily closing price per session; duplicate dates keep the last supplied row.

The following is a **format example only**, not market history:

```csv
Date,Close,Adj Close,Dividends
2026-01-02,100.0,98.0,0
2026-01-05,101.0,99.0,0
```

The analytics reject weekly, monthly and overly sparse series rather than annualizing them as daily observations. This is a cadence check, not a complete exchange-calendar audit. If adjusted closes are absent, invalid or fail to cover the valid raw series, the entire return calculation falls back to raw closes and reports that basis. Unadjusted returns may omit dividends or include split distortions. A synthetic copy of Close is not treated as genuine dividend-adjusted evidence.

Without a Dividends column, observed cash yield remains missing. Price history alone does not supply profitability, valuation or balance-sheet figures and generally cannot qualify for a supported BUY indicator. Missing news or fundamentals is not evidence of strength.

### Dated company fundamentals

Use **Add dated company fundamentals**, then **Download blank fundamentals template**. The CSV accepts these headers:

```csv
Country,Symbol,AsOf,Currency,Source,profit_margin,roe,debt_eq,revenue_growth,earnings_growth,pe,payout,beta,market_cap
```

- `Country`, `Symbol`, `AsOf` and `Currency` are required. Country uses an app listing-market name, such as `Nigeria` or `United States`.
- `AsOf` is the financial statement's ISO date, `YYYY-MM-DD`. Future dates and statements older than **550 days** are rejected. This freshness rule is not independent verification of the accounts.
- `Currency` must match the stock's actual quote unit, including case-sensitive `GBP`/`GBp` or `ZAR`/`ZAc` distinctions. Nigerian retained data uses NGN.
- `Source` is optional and must be an HTTPS reference without embedded credentials.
- Ratios use decimals: `profit_margin=0.20` means 20%; `payout=0.50` means 50%. **`debt_eq` uses percentage points**, so 80 means 80%. P/E is a multiple; market cap is in the stated currency.
- Leave unknown fields blank. Supply at least one observed financial field per row. Nonfinite values, unknown columns and duplicate country/ticker rows are rejected; the limit is 2,000 rows.

Inputs are labelled **User import**. Copy figures only from sources you are authorized to use, check periods and units, and do not place credentials in the CSV. Filling a row does not establish a complete investment case. Provider-supplied fundamentals may have different reporting periods and dates that the app cannot independently verify.

## Indicators and their rules

| Indicator | Meaning |
|---|---|
| **BUY** | Meets the current strategy's evidence, trend and buying-risk rules; investigate before committing capital. |
| **SELL** | An exit-review signal for an **existing holding** with sufficiently supported weak evidence and a falling trend. |
| **NOT GOOD TO BUY** | Current usable evidence does not satisfy the buying rules. It is not a prediction that the business will fail. |
| **WAIT FOR DATA** | Price evidence, cadence, coverage, fundamentals or dates are missing/unusable. It is not a negative verdict on the company. |

BUY requires an eligible score of at least **72/100**, a positive six-month historical return, price at or above the 200-day average, and no enumerated buying-rule risk flags. Guards include unconfirmed/non-positive profit margin, earnings payout outside 0–100%, trailing yield above 9%, missing or above-60% annualized volatility, negative equity, non-positive P/E, RSI above 80, reported average volume below 10,000 shares, and strongly negative headline tone. Some guards apply only when the corresponding observation is supplied; absent data is not independently verified as safe.

SELL requires holding mode, eligible fresh evidence, a score below **55**, a negative six-month return and price below the 200-day average. It is an instruction to review an exit, not an automatically executed sale. Costs, taxes, liquidity and newer announcements can change the decision.

Missing/stale evidence takes precedence over a trading conclusion. Imported fundamentals need a valid date within 550 days. Each selected-stock panel shows reasons and rule identifiers; the numerical thresholds are disclosed heuristics, not statistically established profit probabilities.

### Seven-factor percentage score

| Factor | Balanced | Income | Growth |
|---|---:|---:|---:|
| Income: observed dividends and earnings payout | 15% | 30% | 5% |
| Quality: profit margin, ROE and debt/equity | 20% | 20% | 20% |
| Growth: reported revenue and earnings growth | 15% | 5% | 25% |
| Momentum: historical returns and 200-day trend | 20% | 10% | 25% |
| Valuation: trailing P/E | 10% | 10% | 10% |
| Risk: historical volatility and beta | 10% | 15% | 5% |
| News: recent headline tone | 10% | 10% | 10% |

Each factor's effective weight is its strategy weight multiplied by the fraction of underlying inputs available. The percentage score is the average over that available evidence; **Data coverage** is the supported share of the original total weight. One populated field cannot make a whole missing group look complete.

Underlying eligibility requires at least **60% weighted input coverage**, **200 daily observations**, a positive close no more than **seven calendar days old** with no future date, and at least **three reported inputs** among margin, ROE, debt/equity, revenue growth, earnings growth and trailing P/E. Negative reported debt/equity or annualized volatility above 80% excludes a stock from the eligible shortlist. BUY has the additional stricter guards above.

A high trailing yield can follow a collapsing price or one-off payment. Accounting ratios are not normalized for industry, country or fiscal period. Analyst targets, when supplied, are labelled provider opinions with unverified individual dates/assumptions; they do not enter the score. Scenarios and in-sample backtests are also excluded from the score.

## Monthly/annual returns and possible gains or losses

The selected stock's return view has three separate concepts:

- **Observed performance:** trailing one-calendar-month and one-calendar-year returns ending at the latest observed close. A full corresponding interval is required; the start uses the nearest available observation on or before the cutoff, within seven days. These are not shortened-window annualizations. A separate history table shows completed earlier calendar months and omits the latest observed month.
- **Hypothetical historical gain/loss:** applies those past returns to the amount you enter. It is not your actual account P&L and assumes a fractional allocation. A fee is charged per entry and exit; the allocation includes entry cost. Taxes, spreads/slippage and FX are excluded.
- **Future scenarios:** separate 1-month and 12-month historical-resampling simulations. The app does not divide an annual projection by 12 or turn past returns into a promised monthly payment. P10/P50/P90 are simulated percentiles, not calibrated future probabilities or reliable price targets. Losses can exceed displayed cases.

Simulations use 1,000 five-day block-bootstrap paths from up to 756 recent daily returns and require at least 252 daily prices. Stale prices suppress future scenarios while retaining dated historical observations. Adjusted total returns are used only when the series supports them; otherwise the app discloses raw-price returns. Dividends are not added again to an adjusted total return.

The separate **historical dividend run-rate** multiplies affordable whole shares by observed trailing cash dividends, assuming they repeat. Its monthly equivalent is a budgeting average, not a payment schedule or guaranteed monthly profit. Fees affect the modeled affordable shares; taxes and future dividend changes remain excluded.

All gain/loss amounts stay in the selected stock's quote currency/unit. There is no cross-country portfolio profit total or automatic currency conversion.

## News, plain-language briefs and other tools

The news adapter searches Google News by company and ticker/events and Yahoo ticker RSS where supported. Nigeria uses regional Google searches without pretending that `.NGX` is a Yahoo ticker. It merges returned headlines, publication dates, source links and query provenance. Full news coverage needs five distinct, dated, citable HTTPS stories from the past 14 days. Duplicate titles/URLs, common tracking variants, future records, undated stories and stale records do not increase the score.

This is **headline metadata analysis**, not full article reading or an exhaustive deep-web crawl. Returned stories can be irrelevant or wrong. Source failures stay visible; no replacement news is invented. The short buying case, risks and verification checklist describe supplied observations and conditional drivers, not every possible prospect. Open original stories, issuer filings and exchange announcements before acting.

This build does not call the ChatGPT Deep Research connector; that connector was not available in the development session. Its research features use the packaged market/news adapters and disclosed rules.

Other tools remain available:

- **Backtest Lab:** long-or-cash moving-average positions take effect next session and deduct entry/exit costs over a comparable buy-and-hold period. Results are in-sample and omit slippage, tax, FX and cash interest. They do not validate future profitability.
- **Country-aware watchlist:** SQLite stores country, symbol, notes and an optional review price. Existing symbol-only watchlists migrate transactionally while preserving their records; known suffixes infer the legacy market, and bare legacy tickers retain the prior US default. A review price is not an automatic alert.
- **Optional local AI:** install [Ollama](https://ollama.com/) separately and download a model, for example `ollama pull llama3.2:3b`. The News Intelligence tab can summarize retrieved headline metadata through the local Ollama server. It does not read article bodies or alter scores, and it can be inaccurate. Standard research does not require an LLM subscription.

## Connectivity, privacy and limits

Default non-Nigerian prices use [`yfinance`](https://ranaroussi.github.io/yfinance/), unofficial personal-research access to Yahoo Finance. Prices/fundamentals may be delayed, incomplete, stale, rate-limited or blocked. This is not an officially licensed real-time feed. The price observation date differs from the download-check timestamp.

Standard adapter HTTPS destinations include:

```text
query1.finance.yahoo.com
query2.finance.yahoo.com
finance.yahoo.com
fc.yahoo.com
guce.yahoo.com
feeds.finance.yahoo.com
news.google.com
```

Package installation needs PyPI and package-file hosts. Original publishers, issuer reports and the official NGX price-list link use their own destinations. Public adapters need no feed key; access may still be denied by a proxy or provider. Do not disable TLS verification to work around a denial.

Local files to protect:

- `data/watchlist.sqlite3`: watchlist records; back up separately.
- `data/ngx/`: retained authorized Nigerian histories and financial metadata.
- `data/provider-cache/`: Yahoo cache/session data, which may include provider cookies.

Keep those directories/files, `.venv`, logs and local secrets out of distributable ZIPs. No cloud accounts, broker credentials, authentication system, scheduler, push notifications, live WebSocket feed or commercial-data redistribution license is supplied. For public/commercial deployment, use properly licensed feeds and arrange the necessary security and operational controls.

If a request fails, check the country, ticker suffix, input dates, actual quote units, displayed provider error and network access. Clear caches and rerun after a meaningful access change. If port 8501 is occupied, stop the server you started or change its port. Run from a writable extracted folder, not directly inside the ZIP.

## Developer checks and validation status

From the extracted app folder:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app.py dashboard.py engine.py markets.py providers.py research.py signals.py workflow.py nigeria.py financials.py storage.py ollama_helper.py
```

On Windows, use `.venv\Scripts\python.exe` instead of `.venv/bin/python` after creating the environment with your installed Python launcher.

Tests cover scoring, indicators, historical/scenario calculations, missing and stale evidence, cadence and adjusted-price alignment, country identities, feed parsing, NGX imports, financial validation, watchlist migration and mocked application workflows. Synthetic fixtures are test data, not live market observations.

**Live-feed validation remains blocked in the development cloud:** Yahoo, Google and official NGX requests returned proxy tunnel `403 Forbidden`. Relevant network settings remain a separate environment concern; saving a draft does not apply policy or prove feed access. Automated fixtures do not establish live quotes, live news or a profitable recommendation.

## Changes in v3

- One research basket across several countries, with separate country/ticker identities.
- A searchable Nigerian directory and optional retained authorized NGX imports.
- Explainable buying/holder-exit indicators, explicit missing-data results and dated financial imports.
- Calendar-based observed monthly/annual returns, native-currency gain/loss amounts and separately simulated future horizons.
- Daily-cadence validation prevents weekly/monthly rows being annualized as trading days.
- A single coherent adjusted/raw series prevents an old adjusted endpoint from being labelled current.
- Country-aware watchlist migration preserves existing notes and review prices.
