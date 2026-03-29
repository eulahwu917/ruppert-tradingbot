"""
market_scanner.py — Kalshi market opportunity scanner.
Owner: Researcher agent.

Scans Kalshi API for market categories not currently traded by Ruppert,
checks for coverage gaps, and surfaces hypotheses about new signal sources.

Called by research_agent.py — not run standalone.

    Requires Python 3.10+ (uses PEP 604 union type syntax: dict | None, list[str] | None).
"""

import sys
import time
from pathlib import Path
from datetime import date

# Ensure project root on path
# Resolve workspace root and add to path (agents.ruppert.* + config shim)
_AGENTS_ROOT = Path(__file__).parent.parent.parent  # workspace/agents
_WORKSPACE_ROOT = _AGENTS_ROOT.parent               # workspace/
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))


# California-restricted series: sports and election prediction markets
# Geo restriction applies to all California-based participants.
CA_RESTRICTED_SERIES = {
    # Sports
    'KXNBA', 'KXNHL', 'KXMLB', 'KXNFL',
    # Elections
    'KXPRES', 'KXSEC', 'KXHOUSE', 'KXSENATE',
}

# -----------------------------------------------------------------------
# Categories currently traded by Ruppert
# -----------------------------------------------------------------------
CURRENTLY_TRADED_SERIES_PREFIXES = {
    # Weather (high temp)
    'KXHIGH',
    # Crypto
    'KXBTC', 'KXETH', 'KXSOL', 'KXXRP',
    # Economics / Fed
    'KXFOMC', 'KXFED', 'KXCPI', 'KXUNRATE',
    # Geo / Geopolitical (passively scanning)
    'KXUKR',
}

# Known Kalshi series to probe for new opportunities
# These are categories we don't currently have dedicated scanners for
CANDIDATE_SERIES_TO_SCAN = [
    # Weather — humidity / precipitation
    'KXPRECIP', 'KXSNOW', 'KXRAIN',
    # Macro
    'KXGDP', 'KXPCE', 'KXPPI', 'KXNFP', 'KXJOBLESSCLAIMS',
    # Politics
    'KXPRES', 'KXSEC', 'KXHOUSE', 'KXSENATE',
    # Sports
    'KXNFL', 'KXNBA', 'KXMLB', 'KXNHL',
    # Market / Equities
    'KXSPY', 'KXNDX', 'KXDOW', 'KXVIX',
    # Crypto — additional
    'KXAVAX', 'KXLINK', 'KXDOGE',
    # Energy
    'KXOIL', 'KXGAS',
    # Tech events
    'KXAI', 'KXAPPLE', 'KXNVIDIA',
]

# Public API — no auth needed for market discovery
KALSHI_API_BASE = 'https://api.elections.kalshi.com/trade-api/v2'


def _get_with_retry(url: str, params: dict | None = None, timeout: int = 10, max_retries: int = 3):
    """GET with exponential backoff. Returns Response or None."""
    import requests
    delay = 1.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get('Retry-After', delay))
                print(f"  [RateLimit] 429 — waiting {retry_after:.1f}s")
                time.sleep(retry_after)
                delay *= 2
                continue
            if resp.status_code >= 500:
                time.sleep(delay)
                delay *= 2
                continue
            return resp
        except Exception as e:
            print(f"  [RequestError] {e} — retrying in {delay:.1f}s")
            time.sleep(delay)
            delay *= 2
    return None


def scan_series(series_ticker: str) -> dict:
    """
    Probe a Kalshi series for open markets.
    Returns summary: {series, count, sample_titles, volume_estimate}.
    """
    url = f"{KALSHI_API_BASE}/markets"
    params = {'series_ticker': series_ticker, 'status': 'open', 'limit': 20}
    resp = _get_with_retry(url, params=params, timeout=10)

    if resp is None or resp.status_code != 200:
        return {
            'series': series_ticker,
            'status': 'unreachable',
            'count': 0,
            'sample_titles': [],
            'volume_estimate': 0,
        }

    data = resp.json()
    markets = data.get('markets', [])

    if not markets:
        return {
            'series': series_ticker,
            'status': 'no_open_markets',
            'count': 0,
            'sample_titles': [],
            'volume_estimate': 0,
        }

    sample_titles = [m.get('title', '') for m in markets[:3]]
    # volume_fp is a float string like "1234.56"
    total_volume = sum(
        float(m.get('volume_fp', '0') or '0') for m in markets
    )

    return {
        'series': series_ticker,
        'status': 'found',
        'count': len(markets),
        'sample_titles': sample_titles,
        'volume_estimate': round(total_volume, 2),
    }


def scan_all_candidates(candidates: list[str] | None = None) -> list[dict]:
    """
    Scan a list of series candidates for open market opportunities.
    Returns list of result dicts sorted by volume descending.
    """
    targets = candidates or CANDIDATE_SERIES_TO_SCAN
    results = []

    print(f"[Scanner] Probing {len(targets)} candidate series...")
    for series in targets:
        result = scan_series(series)
        results.append(result)
        status = result['status']
        count = result['count']
        vol = result['volume_estimate']
        print(f"  {series:20s} -> {status:20s} | {count} markets | ${vol:,.0f} vol")
        time.sleep(0.2)  # courteous rate limiting

    # Sort: found first, then by volume
    results.sort(key=lambda r: (0 if r['status'] == 'found' else 1, -r['volume_estimate']))
    return results


def classify_opportunity(result: dict) -> dict:
    """
    Classify a scan result as an opportunity.
    Returns classification dict with recommendation.
    """
    series = result['series']
    status = result['status']
    count = result['count']
    volume = result['volume_estimate']
    titles = result['sample_titles']

    # Skip empty series
    if status != 'found' or count == 0:
        return {
            'series': series,
            'recommendation': 'SKIP',
            'reason': 'No open markets found',
            'priority': 0,
        }

    # California geo restriction: reject before scoring
    if series in CA_RESTRICTED_SERIES:
        return {
            'series': series,
            'count': count,
            'volume': volume,
            'sample_titles': titles,
            'recommendation': 'RESTRICTED',
            'score': 0,
            'reasons': ['California geo restriction — sports/election markets not legally tradeable from CA'],
            'priority': -1,
        }

    # Heuristic scoring
    score = 0
    reasons = []

    # High volume = liquidity = tradeable
    if volume > 100_000:
        score += 3
        reasons.append(f'High volume (${volume:,.0f})')
    elif volume > 10_000:
        score += 2
        reasons.append(f'Medium volume (${volume:,.0f})')
    elif volume > 1_000:
        score += 1
        reasons.append(f'Low-medium volume (${volume:,.0f})')
    else:
        reasons.append(f'Low volume (${volume:,.0f}) — liquidity risk')

    # More markets = more opportunities
    if count >= 10:
        score += 2
        reasons.append(f'{count} open markets — rich opportunity set')
    elif count >= 5:
        score += 1
        reasons.append(f'{count} open markets')

    # Prefer known-predictable categories
    predictable_keywords = ['cpi', 'gdp', 'nfp', 'unemployment', 'rate', 'fed', 'fomc',
                            'temperature', 'high temp', 'btc', 'eth']
    title_text = ' '.join(titles).lower()
    if any(kw in title_text for kw in predictable_keywords):
        score += 2
        reasons.append('Predictable/quantifiable market type')

    # Map score to recommendation
    if score >= 5:
        recommendation = 'PURSUE'
    elif score >= 3:
        recommendation = 'MONITOR'
    else:
        recommendation = 'PASS'

    return {
        'series': series,
        'count': count,
        'volume': volume,
        'sample_titles': titles,
        'recommendation': recommendation,
        'score': score,
        'reasons': reasons,
        'priority': score,
    }


def check_economic_calendar_gaps() -> list[dict]:
    """
    Identify economic indicator categories on Kalshi that we don't cover.
    Placeholder — expands as we discover more series.
    Returns list of gap findings.
    """
    gaps = []

    covered_econ_series = {'KXFOMC', 'KXFED', 'KXCPI', 'KXUNRATE'}

    # Known Kalshi econ series (expand this list as discovered)
    known_econ_series = {
        'KXGDP': 'GDP growth rate',
        'KXPCE': 'PCE inflation',
        'KXPPI': 'Producer Price Index',
        'KXNFP': 'Non-Farm Payrolls',
        'KXJOBLESSCLAIMS': 'Initial Jobless Claims',
        'KXCPI': 'CPI (covered)',
        'KXFOMC': 'FOMC rate decision (covered)',
        'KXUNRATE': 'Unemployment rate (covered)',
        'KXFED': 'Fed funds rate (covered)',
    }

    for series, description in known_econ_series.items():
        if series not in covered_econ_series:
            gaps.append({
                'series': series,
                'description': description,
                'gap_type': 'uncovered_econ_series',
                'hypothesis': f'We have BLS/FRED data for {description} — could build edge model similar to CPI scanner',
            })

    return gaps


def generate_signal_hypotheses() -> list[dict]:
    """
    Surface hypotheses about new signal sources for new market categories.
    Pure reasoning — no API calls. Returns list of hypothesis dicts.
    """
    hypotheses = [
        {
            'category': 'Equity index markets (SPY/NDX/DOW)',
            'signal_sources': ['options implied vol', 'VIX term structure', 'Fed minutes sentiment'],
            'hypothesis': 'Options market prices reflect short-term directional bias. If SPY options IV skew points strongly bearish, YES on "SPY closes below X" may be underpriced.',
            'data_source_needed': 'CBOE options data, Yahoo Finance, or paid feed',
            'effort': 'medium',
            'priority': 'high',
        },
        {
            'category': 'GDP / PCE markets',
            'signal_sources': ['GDPNow (Atlanta Fed)', 'Nowcast models', 'BEA advance estimate'],
            'hypothesis': 'Atlanta Fed GDPNow is public and updated in real-time. If GDPNow diverges significantly from market consensus, there may be a tradeable edge on GDP outcome markets.',
            'data_source_needed': 'Atlanta Fed GDPNow API (free, public)',
            'effort': 'low',
            'priority': 'high',
        },
        {
            'category': 'NFP (Non-Farm Payrolls)',
            'signal_sources': ['ADP employment report', 'weekly jobless claims', 'ISM employment subindex'],
            'hypothesis': 'ADP payroll data releases 2 days before NFP and is correlated. If ADP surprised high/low, NFP Kalshi markets may not have updated. Early-mover edge possible.',
            'data_source_needed': 'BLS ADP data (free), already partially covered in economics_client.py',
            'effort': 'low',
            'priority': 'high',
        },
        {
            'category': 'Precipitation / snow markets',
            'signal_sources': ['NOAA QPF (quantitative precip forecast)', 'NWS point forecasts', 'GFS ensemble'],
            'hypothesis': 'We already have NOAA station access via ghcnd_client. QPF endpoint provides precip probability. Could extend weather scanner to cover precipitation markets.',
            'data_source_needed': 'NOAA Weather.gov API (free, already partially integrated)',
            'effort': 'low',
            'priority': 'medium',
        },
        {
            'category': 'Crypto altcoins (SOL, XRP, AVAX)',
            'signal_sources': ['On-chain metrics', 'funding rate', 'correlation to BTC'],
            'hypothesis': 'BTC directional signal may propagate to altcoins with lag. If BTC signal is strong bull and alts are pricing lower correlation, YES on alts above strike may be underpriced.',
            'data_source_needed': 'Same crypto_client feeds, crypto_smart_money.json',
            'effort': 'low',
            'priority': 'medium',
        },
        {
            'category': 'VIX / volatility markets',
            'signal_sources': ['VIX spot vs futures', 'VVIX', 'term structure'],
            'hypothesis': 'When VIX is in steep backwardation (spot > futures), market expects vol to fall. Kalshi VIX markets may price this inefficiently during stress periods.',
            'data_source_needed': 'CBOE VIX data (free via yfinance or FRED)',
            'effort': 'medium',
            'priority': 'low',
        },
    ]
    return hypotheses
