"""Multi-country discovery, transparent decisions and return analysis in one place."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

from engine import backtest_sma
from markets import MARKETS, market_symbols, resolve_symbols, search_companies
from research import evaluate_unified, evidence_brief
from signals import decision_signal, performance_report
from financials import FUNDAMENTALS_TEMPLATE, parse_fundamentals
from storage import save
from workflow import instrument_key, import_research
from exports import safe_csv

MAX_STOCKS = 48


@st.cache_data(ttl=900, max_entries=120, show_spinner=False)
def find_companies(query: str, country: str):
    return search_companies(query, country, limit=15)


def ranking_frame(items, goal, holding=False):
    rows = []
    for item in items:
        m = item['metrics']
        rating = evaluate_unified(m, item['news'], info=item.get('info'), goal=goal)
        signal = decision_signal(item, goal=goal, holding=holding)
        performance = performance_report(item, include_scenarios=False)
        observed = performance.get('observed', {})
        month, year = observed.get('month'), observed.get('year')
        rows.append({
            'Instrument': item.get('id', instrument_key(item['country'], item['symbol'])),
            'Country': item['country'], 'Ticker': item['symbol'], 'Company': m['name'],
            'Indicator': signal['action'], 'Brief analysis': signal['summary'],
            'Research score (%)': rating['score'], 'Data coverage (%)': rating['coverage'] * 100,
            'Evidence sufficient': rating['eligible'] and signal['action'] != 'WAIT FOR DATA',
            'Close': m['price'], 'Currency': m['currency'],
            'Observed 1m return (%)': None if not month else month['return'] * 100,
            'Observed 1y return (%)': None if not year else year['return'] * 100,
            'Dividend yield (%)': None if m['yield_12m'] is None else m['yield_12m'] * 100,
            'Headlines': item['news']['count'], 'Price date': m['as_of'],
            'Price source': item.get('source'), 'Strategy': goal,
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ['Evidence sufficient', 'Research score (%)', 'Data coverage (%)', 'Instrument'],
        ascending=[False, False, False, True], na_position='last').reset_index(drop=True)


def _country_inputs(country, expanded=True):
    market = MARKETS[country]
    code = market['code']
    lookup_key, basket_key = f'company_matches_{code}', f'research_basket_{code}'
    seeds = market_symbols(country)
    with st.expander(country + ' · ' + market['currency'], expanded=expanded):
        if market.get('note'):
            st.caption(market['note'])
        with st.form(f'lookup_{code}'):
            query = st.text_input(f'Find companies in {country}', placeholder='Company name, ticker' + (', or sector' if country == 'Nigeria' else ''))
            lookup = st.form_submit_button(f'Find stocks in {country}')
        if lookup:
            try:
                st.session_state[lookup_key] = find_companies(query.strip(), country)
                if not st.session_state[lookup_key]:
                    st.info('No matching company returned. Try the exchange ticker or another company name.')
            except Exception as exc:
                st.session_state[lookup_key] = []
                st.error('Company search unavailable: ' + str(exc)[:250])
        matches = st.session_state.get(lookup_key, [])
        if matches:
            labels = {x['symbol']: f"{x['name']} · {x['symbol']}" for x in matches}
            choices = st.multiselect(f'Matching companies in {country}', list(labels), format_func=labels.get,
                                     default=[matches[0]['symbol']], key=f'hits_{code}')
            if st.button(f'Add selected {country} companies', disabled=not choices):
                current = st.session_state.get(basket_key, seeds[:2])
                st.session_state[basket_key] = list(dict.fromkeys(current + choices))
        if basket_key not in st.session_state:
            st.session_state[basket_key] = seeds[:2]
        options = list(dict.fromkeys(seeds + [x['symbol'] for x in matches] + st.session_state[basket_key]))
        selected = st.multiselect(f'{country} research basket', options, key=basket_key)
        manual = st.text_input(f'Additional {country} tickers', placeholder='Comma-separated local or exchange tickers', key=f'manual_{code}')
        uploaded = st.file_uploader(f'Import {country} price CSVs (optional)', type=['csv'],
                                    accept_multiple_files=True, key=f'imports_{code}')
        names, currency, remember = {}, market['currency'].split(' / ')[0], False
        if uploaded:
            names_text = st.text_area(f'Company names for {country} imports (optional)',
                                      placeholder='TICKER=Company name', key=f'names_{code}')
            for line in names_text.splitlines():
                if '=' in line:
                    symbol, company = line.split('=', 1)
                    names[symbol.strip().upper()] = company.strip()[:80]
            currency = st.text_input(f'{country} CSV currency / price unit', value=currency, key=f'import_currency_{code}', max_chars=12)
            if country == 'Nigeria':
                remember = st.checkbox('Remember NGX imports on this computer', value=False,
                                       help='Retains your authorized prices and dated fundamentals locally in data/ngx for later research.')
        st.caption('One daily-history CSV per stock, named with its ticker. Required: Date, Close. Optional: Adj Close, Dividends. Starter baskets are examples, not complete exchange listings.')
    return {'country': country, 'selected': selected, 'manual': manual, 'uploaded': uploaded,
            'names': names, 'currency': currency, 'remember': remember}


def _show_signal(item, goal, holding):
    signal = decision_signal(item, goal=goal, holding=holding)
    with st.container(border=True):
        icon = {'BUY': '🟢', 'SELL': '🔴', 'NOT GOOD TO BUY': '🟠', 'WAIT FOR DATA': '⚪'}[signal['action']]
        st.markdown('### ' + icon + ' ' + signal['action'])
        st.write(signal['summary'])
        for reason in signal.get('reasons', [])[:4]:
            st.write('• ' + reason)
        if signal.get('blockers'):
            st.warning(' · '.join(signal['blockers']))
        st.caption('Rule-based research indicator · ' + signal['rule_version'] +
                   ' · SELL applies to existing holdings. It is not an order or a guaranteed outcome.')
    return signal


def _show_brief(item):
    brief = evidence_brief(item['metrics'], item['news'], info=item.get('info'))
    st.subheader('The stock in plain language')
    a, b = st.columns(2)
    with a:
        st.markdown('#### Why consider buying?')
        for text in brief['strengths'][:3]:
            st.write('• ' + text)
    with b:
        st.markdown('#### Why avoid or reconsider?')
        for text in brief['risks'][:3]:
            st.write('• ' + text)
        if not brief['risks']:
            st.write('No specific red flag was identified from the available inputs. Risks can still be missing.')
    with st.expander('Checks before acting'):
        for text in brief['verify']:
            st.write('• ' + text)
        st.link_button('Find issuer reports and announcements', 'https://www.google.com/search?q=' +
                       quote_plus(item['metrics']['name'] + ' investor relations annual report'))
        if item['country'] == 'Nigeria':
            st.link_button('Check the official NGX price list', 'https://ngxgroup.com/exchange/data/equities-price-list/')
        else:
            st.link_button('Check the quote source', 'https://finance.yahoo.com/quote/' + quote_plus(item['symbol']))


def _show_returns(item):
    st.subheader('Monthly & annual returns')
    m = item['metrics']
    a, b = st.columns(2)
    investment = a.number_input(f'Amount to analyse ({m["currency"]})', min_value=0.0, value=10000.0,
                                step=100.0, key='report_investment')
    fee = b.number_input('Fee per entry / exit (%)', min_value=0.0, max_value=5.0, value=0.15,
                          step=0.05, key='report_fee')
    report = performance_report(item, investment=investment, fee_pct=fee, include_scenarios=True)
    st.caption('Observed returns describe past periods. Gain/loss amounts apply those returns to your chosen amount and are not your actual account profit. Currency stays native; fees exclude tax, FX and slippage.')
    month, year = report['observed'].get('month'), report['observed'].get('year')
    a, b = st.columns(2)
    for column, title, period in [(a, 'Trailing 1 month', month), (b, 'Trailing 1 year', year)]:
        if period:
            column.metric(title + ' return', f"{period['return']:+.2%}")
            column.metric(title + ' illustrative net gain / loss', f"{m['currency']} {period['net_gain']:+,.2f}")
            column.caption(f"{period['start_date']} to {period['end_date']}")
        else:
            column.metric(title + ' return', 'Not enough valid history')
    scenarios = report.get('scenarios', {})
    if scenarios:
        st.markdown('#### Future scenarios — profits are uncertain')
        rows = []
        for key, label in [('1m', 'Next 1 month'), ('12m', 'Next 12 months')]:
            scenario = scenarios.get(key)
            if scenario:
                for field, name in [('p10', 'P10'), ('median', 'P50'), ('p90', 'P90')]:
                    net_key = {'p10': 'net_p10', 'median': 'net_median', 'p90': 'net_p90'}[field]
                    rows.append({'Horizon': label, 'Historical-resampling scenario': name,
                                 'Return (%)': scenario[field] * 100,
                                 'Net gain / loss': scenario.get(net_key, scenario.get(field + '_gain')),
                                 'Currency': m['currency']})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={'Return (%)': st.column_config.NumberColumn(format='%.2f%%'),
                                    'Net gain / loss': st.column_config.NumberColumn(format='%.2f')})
        st.caption('P10/P50/P90 come from separate 1-month and 12-month five-day block-bootstrap simulations. They are not calibrated probabilities or reliable price forecasts; losses can exceed simulated cases.')
    for warning in report.get('warnings', []):
        st.caption(warning)
    income = report.get('income')
    if income:
        st.write(f"**Historical dividend run-rate:** {m['currency']} {income.get('annual', income.get('annual_run_rate', 0)):,.2f} annually · "
                 f"{m['currency']} {income['monthly_equivalent']:,.2f} monthly budgeting equivalent.")
        st.caption('Not a promised dividend or monthly payment schedule; dividends are already reflected when adjusted total returns are used.')
    monthly = report.get('monthly_returns', [])
    if monthly:
        with st.expander('Completed calendar-month history'):
            table = pd.DataFrame(monthly)
            if 'return' in table:
                table['Return (%)'] = table.pop('return') * 100
            st.dataframe(table, hide_index=True, use_container_width=True,
                         column_config={'Return (%)': st.column_config.NumberColumn(format='%.2f%%')})
    return report


def render_discovery(countries, goal, fetch, news_fetch, show_assessment, show_headlines):
    if isinstance(countries, str):
        countries = [countries]
    countries = list(dict.fromkeys(countries))
    st.markdown('### Research several markets. Understand the decision.')
    st.write('Build one basket across Nigeria and other countries. Get a short explanation, a Buy / Sell / Not good to buy indicator, and clearly separated historical returns and future scenarios.')
    if not countries:
        st.info('Select at least one country in the sidebar.')
        return
    st.caption('Selected markets: ' + ' · '.join(countries) + f' · Up to {MAX_STOCKS} stocks in one batch. No currency conversion is applied.')
    columns = st.columns(2 if len(countries) > 1 else 1)
    inputs = []
    for index, country in enumerate(countries):
        with columns[index % len(columns)]:
            inputs.append(_country_inputs(country, expanded=len(countries) <= 2))
    with st.expander('Add dated company fundamentals (optional)'):
        fundamentals_file = st.file_uploader('Fundamentals CSV for any selected countries', type=['csv'], key='fundamentals_upload')
        st.download_button('Download blank fundamentals template', FUNDAMENTALS_TEMPLATE, 'MIKEIZU_fundamentals_template.csv', 'text/csv')
        st.caption('Fill with figures from authorized reports: Country, Symbol, AsOf, Currency and observed financial fields. Ratios use decimals (0.20 = 20%); debt_eq uses percentage points. Unknown figures stay blank. Inputs are dated and labelled user-supplied.')
    holding = st.toggle('Review this basket as stocks I already own', value=False,
                        help='Enables SELL when the rules identify sufficient bearish evidence. For new purchases, that evidence shows NOT GOOD TO BUY.')
    if st.button('Run multi-country deep research', type='primary', use_container_width=True):
        try:
            financials = parse_fundamentals(fundamentals_file) if fundamentals_file else {}
            online, imported = {}, {}
            for entry in inputs:
                country = entry['country']
                for symbol in resolve_symbols(','.join(entry['selected'] + [entry['manual']]), country):
                    online[instrument_key(country, symbol)] = (symbol, country)
                for uploaded in entry['uploaded']:
                    symbols = resolve_symbols(Path(uploaded.name).stem, country)
                    if len(symbols) != 1:
                        raise ValueError('Each file must use one valid ticker as its filename.')
                    key = instrument_key(country, symbols[0])
                    if key in imported:
                        raise ValueError('Duplicate import for ' + key)
                    imported[key] = (uploaded, entry)
                    online.pop(key, None)
            count = len(online) + len(imported)
            if not count or count > MAX_STOCKS:
                raise ValueError(f'Choose between 1 and {MAX_STOCKS} stocks across the selected countries.')
            collected, errors = [], []
            progress = st.progress(0, text='Gathering company evidence, daily history and regional news…')
            with ThreadPoolExecutor(max_workers=3) as pool:
                jobs = {pool.submit(fetch, symbol, True, country, financials): key
                        for key, (symbol, country) in online.items()}
                for key, (uploaded, entry) in imported.items():
                    jobs[pool.submit(import_research, uploaded, entry['country'], entry['names'], news_fetch,
                                     financials, entry['currency'], entry['remember'])] = key
                for completed, future in enumerate(as_completed(jobs), 1):
                    try:
                        collected.append(future.result())
                    except Exception as exc:
                        errors.append(jobs[future] + ': ' + str(exc)[:300])
                    progress.progress(completed / count, text=f'Reviewed {completed} of {count} stocks')
            st.session_state['combined_scan'] = {'countries': countries, 'items': collected, 'errors': errors,
                                                 'checked': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                                 'requested': count, 'run_id': datetime.now(timezone.utc).isoformat()}
        except ValueError as exc:
            st.error(str(exc))
    scan = st.session_state.get('combined_scan')
    if not scan or scan.get('countries') != countries:
        st.info('Choose stocks in the country baskets, then run research. Nigerian names can be researched for news immediately; prices and trading indicators need authorized NGX history and sufficient financial inputs.')
        return
    if scan['errors']:
        with st.expander('Requests that could not complete', expanded=True):
            for error in scan['errors']:
                st.error(error)
    if not scan['items']:
        st.warning('No stock research could be assembled. Check the reported input and provider errors.')
        return
    frame = ranking_frame(scan['items'], goal, holding)
    a, b, c, d = st.columns(4)
    a.metric('Countries reviewed', frame['Country'].nunique())
    b.metric('Stocks researched', f"{len(frame)} / {scan['requested']}")
    c.metric('BUY indicators', int((frame['Indicator'] == 'BUY').sum()))
    d.metric('Recent headlines', int(frame['Headlines'].sum()))
    st.subheader('Your multi-country shortlist')
    st.caption('WAIT FOR DATA means the evidence is missing or stale. It is not a negative verdict on the business. Research percentages measure alignment with disclosed rules, not profit probabilities. Results checked: ' + scan['checked'])
    st.dataframe(frame.drop(columns=['Instrument']), hide_index=True, use_container_width=True,
                 column_config={'Research score (%)': st.column_config.ProgressColumn(format='%.1f%%', min_value=0, max_value=100),
                                'Data coverage (%)': st.column_config.ProgressColumn(format='%.0f%%', min_value=0, max_value=100),
                                'Close': st.column_config.NumberColumn(format='%.2f'),
                                'Observed 1m return (%)': st.column_config.NumberColumn(format='%.2f%%'),
                                'Observed 1y return (%)': st.column_config.NumberColumn(format='%.2f%%')})
    st.download_button('Download multi-country research ranking', safe_csv(frame), 'MIKEIZU_global_research_v3.csv', 'text/csv')
    gaps = [item for item in scan['items'] if item.get('price_error') or item.get('news_error')]
    if gaps:
        with st.expander('Data coverage and provider problems'):
            for item in gaps:
                st.write(f"**{item['country']} · {item['symbol']}**")
                if item.get('price_error'):
                    st.warning('Price history: ' + item['price_error'])
                if item.get('news_error'):
                    st.caption('News: ' + item['news_error'])
    by_id = {item.get('id', instrument_key(item['country'], item['symbol'])): item for item in scan['items']}
    chosen = st.selectbox('Inspect a researched stock', frame['Instrument'].tolist(),
                          format_func=lambda key: f"{by_id[key]['country']} · {by_id[key]['symbol']} · {by_id[key]['metrics']['name']}")
    item = by_id[chosen]
    selection = (chosen, scan['run_id'])
    if st.session_state.get('last_combined_selection') != selection:
        st.session_state['research'] = item
        st.session_state['last_combined_selection'] = selection
    signal = _show_signal(item, goal, holding)
    _show_brief(item)
    if item['metrics']['price'] is not None:
        report = _show_returns(item)
        if st.checkbox('Show price chart, factor breakdown and strategy check', value=False):
            show_assessment(item, goal)
            column = 'Adj Close' if item['metrics'].get('price_adjusted') and 'Adj Close' in item['prices'] else 'Close'
            st.line_chart(item['prices'][[column]], height=240)
            for warning in item['metrics'].get('data_warnings', []):
                st.warning(warning)
            try:
                backtest = backtest_sma(item['prices'], window=200)
                st.line_chart(backtest['curve'], height=220)
                st.caption('Historical 200-day moving-average strategy with next-session positions and 0.15% entry/exit cost; in-sample, not validated future profitability.')
            except ValueError as exc:
                st.info(str(exc))
    else:
        report = None
        st.info('Monthly/annual returns and profit scenarios are unavailable without valid daily price history. No values are invented.')
    if st.button('Save selected stock to watchlist'):
        save(item['symbol'], country=item['country'])
        st.success('Saved with its country and ticker.')
    show_headlines(item['news'])
    with st.expander('Research sources and decision rules'):
        st.write('Price source: ' + item['source'])
        st.write('Price date: ' + str(item['metrics']['as_of']) + ' · Download checked: ' + item['fetched'])
        if item['info'].get('fundamentals_as_of'):
            st.write('Financial inputs: ' + item['info'].get('fundamentals_source', 'Provider') + ' · ' + item['info']['fundamentals_as_of'])
        for query in item.get('news_queries', []):
            st.write(query)
        st.write('Decision reason codes:', signal.get('reason_codes', []))
        st.caption('Headline metadata is not full article text. This app does not claim an exhaustive web crawl or a statistically validated profit prediction. The latest source documents remain essential.')
    exported = {'country': item['country'], 'symbol': item['symbol'], 'checked': item['fetched'],
                'signal': signal, 'metrics': item['metrics'], 'performance': report,
                'sources': item.get('news_queries', [])}
    st.download_button('Download this stock research brief (JSON)', json.dumps(exported, default=str, indent=2),
                       MARKETS[item['country']]['code'] + '_' + item['symbol'] + '_brief.json', 'application/json')
