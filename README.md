# my-stock-app
stock search app

## Download MIKEIZU Stock Intelligence PRO v3

[Download the latest app ZIP](https://github.com/Mikeizu/my-stock-app/raw/refs/heads/main/downloads/MIKEIZU_Stock_Intelligence_PRO_v3.zip)

Extract the ZIP into a writable folder. Install Python 3.11–3.13, then on Windows double-click `START_WINDOWS.bat` in the extracted app folder. On macOS/Linux, run `bash run_linux_mac.sh` from that folder. Internet is needed for dependencies and available external data.

## What is new

- Research up to **8 countries together**, with up to **48 stocks** in a combined basket.
- Search a **36-company Nigerian directory** and retain authorized NGX daily history and dated financial inputs for reuse.
- Read plain-language reasons behind **BUY**, holding-only **SELL**, **NOT GOOD TO BUY**, and **WAIT FOR DATA** research indicators.
- Compare observed trailing monthly/yearly returns and hypothetical fee-adjusted gains/losses. Future 1-month and 12-month scenarios stay separately labelled and can show losses.
- Keep watchlists by country and ticker, preserving existing notes. Export research and inspect cited headlines.

**Nigerian price data:** the directory contains company identities, not live quotes. Price-based Nigerian signals need authorized daily CSV history plus sufficient dated fundamentals. No automated live NGX feed is bundled. `.NGX` is an internal app identifier, not a Yahoo symbol.

**Research limits:** indicators use disclosed rules, not a validated prediction model. No percentage is a profit probability and no monthly/annual profit is promised. News analysis uses returned headline metadata, not every article or website. Default public feeds may be delayed, incomplete, restricted or rate-limited. Live Yahoo/Google/NGX connectivity was blocked by the development cloud's proxy; this is distinct from automated tests with controlled fixtures.

See the [full user guide and methodology](MIKEIZU_Stock_Intelligence_PRO/README.md). [Previous v2 download](downloads/MIKEIZU_Stock_Intelligence_PRO_v2.zip) remains available.

Validation: **170 automated tests passed** against the extracted v3 distribution on Python 3.12/Linux. Real-browser checks covered the dashboard, Nigerian directory discovery and the missing-feed path. Windows launch instructions are included; a native Windows run was not performed in this cloud.
