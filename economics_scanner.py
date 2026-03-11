"""
Economics Market Scanner
Scans Kalshi economics markets and uses BLS/FRED data to identify edge.

ALL opportunities flagged here are SEMI-AUTO — David must approve before any trade executes.

Author: Ruppert (AI Trading Analyst)
Updated: 2026-03-10
"""
import requests
import sys
from datetime import datetime, date
from economics_client import (
    get_cpi_data,
    get_fed_rate,
    get_unemployment,
    get_gdp_data,
    get_economic_signal,
    get_upcoming_releases,
)

BASE = 'https://api.elections.kalshi.com/trade-api/v2'
HEADERS = {'User-Agent': 'KalshiEconBot/1.0'}

# Known economics series on Kalshi (verified active as of 2026-03-10)
ACTIVE_ECON_SERIES = [
    'KXCPI',         # Monthly CPI MoM — HIGHEST VOLUME
    'KXFED',         # Fed Funds Target Upper Bound — HIGHEST VOLUME
    'KXECONSTATU3',  # US Unemployment Rate monthly — MEDIUM VOLUME
    'KXUE',          # Global unemployment (Germany, France) — LOW VOLUME
    'KXWRECSS',      # Country recession markets — MEDIUM VOLUME
]

# Minimum edge threshold to flag an opportunity
MIN_EDGE = 0.15  # 15% edge minimum
MIN_VOLUME = 100  # Minimum market volume (contracts) to consider

# Confidence filters
CONFIDENCE_FILTER = ['medium', 'high']  # Only include these confidence levels


def fetch_open_markets(series_ticker: str, limit: int = 50) -> list:
    """Fetch open markets for a given series ticker."""
    try:
        r = requests.get(
            f'{BASE}/markets',
            params={'series_ticker': series_ticker, 'status': 'open', 'limit': limit},
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            print(f'[EconScanner] HTTP {r.status_code} for series {series_ticker}')
            return []
        return r.json().get('markets', [])
    except Exception as e:
        print(f'[EconScanner] Error fetching {series_ticker}: {e}')
        return []


def analyze_market(market: dict, econ_data: dict) -> dict | None:
    """
    Analyze a single market and return an opportunity dict if edge exists.
    Returns None if no significant edge.
    """
    ticker = market.get('ticker', '')
    title = market.get('title', '')
    yes_ask = market.get('yes_ask')
    volume = market.get('volume', 0)
    series = market.get('series_ticker', '')

    # Skip illiquid markets
    if volume < MIN_VOLUME:
        return None
    if yes_ask is None or yes_ask <= 0:
        return None

    # Skip near-100% or near-0% (no real market)
    if yes_ask >= 97 or yes_ask <= 2:
        return None

    market_prob = yes_ask / 100.0

    # KXFED — well-arbitraged by CME FedWatch, limited edge from FRED data alone.
    # NOTE: KXFED-27APR markets show non-monotonic pricing (tariff uncertainty),
    # meaning market is pricing a bimodal distribution. Our naive model is insufficient.
    # Skip KXFED entirely unless we have CME FedWatch integration.
    if series == 'KXFED' or ticker.startswith('KXFED'):
        return None  # Disabled: requires CME FedWatch data for reliable signals

    # For all other series
    signal = get_economic_signal(title, market_prob)

    if signal.get('edge') is None:
        return None

    edge = signal['edge']
    confidence = signal.get('confidence', 'low')

    # Filter on edge threshold and confidence
    if abs(edge) < MIN_EDGE:
        return None
    if confidence not in CONFIDENCE_FILTER:
        return None

    return _build_opportunity(market, signal, market_prob)


def _build_opportunity(market: dict, signal: dict, market_prob: float) -> dict:
    """Build a standardized opportunity dict."""
    edge = signal['edge']
    yes_ask = market.get('yes_ask', 0)
    no_ask = market.get('no_ask', 0)

    # Determine bet direction
    if edge > 0:
        # Model thinks probability is higher than market → BET YES
        bet_direction = 'YES'
        bet_price = yes_ask  # cost in cents (market ask — actual fill may differ)
        implied_return = round((100 - yes_ask) / yes_ask, 3) if yes_ask > 0 else None
    else:
        # Model thinks probability is lower than market → BET NO
        bet_direction = 'NO'
        # NOTE: no_ask can be wide (illiquid NO side). Use limit orders near 100 - yes_ask
        # for better fill prices. The fair NO value ≈ 100 - yes_bid (not no_ask).
        fair_no_price = 100 - yes_ask  # theoretical fair NO price
        bet_price = fair_no_price  # use theoretical price, not ask
        implied_return = round((100 - fair_no_price) / fair_no_price, 3) if fair_no_price > 0 else None

    return {
        'ticker': market.get('ticker'),
        'title': market.get('title'),
        'series': market.get('series_ticker'),
        'yes_ask': yes_ask,
        'no_ask': no_ask,
        'volume': market.get('volume', 0),
        'market_prob': round(market_prob, 3),
        'model_prob': signal.get('model_prob'),
        'edge': round(edge, 3),
        'abs_edge': round(abs(edge), 3),
        'confidence': signal.get('confidence'),
        'signal_source': signal.get('signal_source'),
        'bet_direction': bet_direction,
        'bet_price_cents': bet_price,
        'implied_return': implied_return,
        'reasoning': signal.get('reasoning', ''),
        'type': 'economics',
        'auto_trade': False,            # ALWAYS semi-auto
        'requires_human_review': True,  # David must approve
        'flagged_at': datetime.now().isoformat(),
    }


def find_econ_opportunities(verbose: bool = True) -> list:
    """
    Main scanner: finds economics market opportunities with edge > 15%.
    All results require human approval before trading.
    """
    print('[EconScanner] Starting economics market scan...')

    # Pre-fetch all economic data once (avoid multiple API calls)
    print('[EconScanner] Fetching BLS/FRED data...')
    econ_data = {
        'cpi': get_cpi_data(),
        'fed': get_fed_rate(),
        'unemployment': get_unemployment(),
        'gdp': get_gdp_data(),
    }

    cpi_mom = econ_data["cpi"].get("mom_change_pct")
    print(f'[EconScanner] CPI: {cpi_mom:.3f}% MoM, {econ_data["cpi"].get("yoy_change_pct", "?")}% YoY'
          if cpi_mom is not None else '[EconScanner] CPI: data unavailable')
    print(f'[EconScanner] Fed: {econ_data["fed"].get("target_upper_bound", "?")}% upper bound')
    print(f'[EconScanner] Unemployment: {econ_data["unemployment"].get("latest_rate", "?")}%')
    print(f'[EconScanner] GDP QoQ: {econ_data["gdp"].get("qoq_growth_pct", "?")}%')

    # Prime the in-process cache so per-market analysis doesn't re-fetch
    import economics_client as _ec
    if econ_data['cpi']:
        _ec._cache_set('cpi_data', econ_data['cpi'])
        _ec._cache_set('cpi_data_fred', econ_data['cpi'])
    if econ_data['fed']:
        _ec._cache_set('fed_rate', econ_data['fed'])
    if econ_data['unemployment']:
        _ec._cache_set('unemployment', econ_data['unemployment'])

    # Upcoming releases
    upcoming = get_upcoming_releases()
    if upcoming:
        print(f'[EconScanner] UPCOMING RELEASES:')
        for rel in upcoming:
            print(f'  {rel["event"]} on {rel["date"]} ({rel["days_away"]}d away) — {rel["series"]}')

    # Scan each active series
    all_markets = []
    series_counts = {}
    for series in ACTIVE_ECON_SERIES:
        markets = fetch_open_markets(series)
        series_counts[series] = len(markets)
        all_markets.extend(markets)
        if verbose:
            print(f'[EconScanner] {series}: {len(markets)} open markets')

    print(f'[EconScanner] Total open markets: {len(all_markets)}')

    # Analyze each market
    opportunities = []
    for m in all_markets:
        try:
            opp = analyze_market(m, econ_data)
            if opp:
                opportunities.append(opp)
        except Exception as e:
            print(f'[EconScanner] Error analyzing {m.get("ticker")}: {e}')

    # Sort by absolute edge (best first)
    opportunities.sort(key=lambda x: x.get('abs_edge', 0), reverse=True)

    print(f'\n[EconScanner] Found {len(opportunities)} opportunities with edge > {MIN_EDGE:.0%}')
    print('[EconScanner] *** ALL require David\'s approval before trading ***\n')

    if verbose and opportunities:
        print(f'{"Ticker":<35} {"Direction":>9} {"Mkt%":>5} {"Model%":>7} {"Edge":>6} {"Conf":>7} {"Vol":>8}')
        print('-' * 85)
        for o in opportunities:
            model_pct = f'{o["model_prob"]:.1%}' if o["model_prob"] is not None else '?'
            print(
                f'{o["ticker"]:<35} {o["bet_direction"]:>9} {o["market_prob"]:>5.0%} '
                f'{model_pct:>7} {o["edge"]:>+6.2f} {o["confidence"]:>7} {o["volume"]:>8,}'
            )
            print(f'  Reasoning: {o["reasoning"][:100]}')

    return opportunities


def get_economics_summary() -> dict:
    """
    Return a brief summary of current economics indicators.
    Used by the main dashboard/scanner aggregator.
    """
    cpi = get_cpi_data()
    fed = get_fed_rate()
    unemp = get_unemployment()
    upcoming = get_upcoming_releases()

    return {
        'cpi_mom': cpi.get('mom_change_pct'),
        'cpi_yoy': cpi.get('yoy_change_pct'),
        'cpi_trend': cpi.get('trend'),
        'fed_upper_bound': fed.get('target_upper_bound'),
        'fed_last_change': fed.get('last_change_direction'),
        'next_fomc': fed.get('next_fomc_date'),
        'unemployment': unemp.get('latest_rate'),
        'unemployment_trend': unemp.get('trend'),
        'upcoming_releases': upcoming,
        'fetched_at': datetime.now().isoformat(),
    }


if __name__ == '__main__':
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    opps = find_econ_opportunities(verbose=True)

    print(f'\n=== SUMMARY ===')
    print(f'Total opportunities: {len(opps)}')
    print(f'High confidence: {len([o for o in opps if o["confidence"] == "high"])}')
    print(f'Medium confidence: {len([o for o in opps if o["confidence"] == "medium"])}')

    if opps:
        best = opps[0]
        print(f'\nBest opportunity:')
        print(f'  {best["ticker"]}')
        print(f'  Bet {best["bet_direction"]} at {best["bet_price_cents"]}c')
        print(f'  Edge: {best["edge"]:+.2f} | Confidence: {best["confidence"]}')
        print(f'  Implied return: {best["implied_return"]:.1%}' if best.get('implied_return') else '')
        print(f'  {best["reasoning"][:200]}')

    print(f'\n*** SEMI-AUTO MODE: All trades require David approval ***')
