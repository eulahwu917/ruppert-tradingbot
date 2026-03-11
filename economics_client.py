"""
Economics Data Client
Fetches CPI, unemployment, Fed rate, GDP data from BLS and FRED public APIs.
No API key required — all free public endpoints.

Author: Ruppert (AI Trading Analyst)
Updated: 2026-03-10
"""
import requests
from datetime import datetime, date, timedelta
import json
import re

BLS_BASE = 'https://api.bls.gov/publicAPI/v1/timeseries/data'
FRED_CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
HEADERS = {'User-Agent': 'KalshiEconBot/1.0 (economics-research)'}

# In-process cache to avoid repeat API calls in a single scan session
# TTL: 1 hour (3600 seconds)
_CACHE: dict = {}
_CACHE_TTL = 3600  # seconds

def _cache_get(key: str):
    import time
    entry = _CACHE.get(key)
    if entry and (time.time() - entry['ts']) < _CACHE_TTL:
        return entry['data']
    return None

def _cache_set(key: str, data):
    import time
    _CACHE[key] = {'data': data, 'ts': time.time()}

# BLS Series IDs
CPI_SERIES = 'CUSR0000SA0'          # CPI-U All Urban Consumers (headline)
CORE_CPI_SERIES = 'CUSR0000SA0L1E'  # CPI Less Food & Energy

# FRED Series IDs
FEDFUNDS_SERIES = 'FEDFUNDS'        # Effective Fed Funds Rate (monthly avg)
DFEDTARU_SERIES = 'DFEDTARU'        # Fed Funds Target Upper Bound (daily)
UNRATE_SERIES = 'UNRATE'            # Unemployment Rate
GDPC1_SERIES = 'GDPC1'              # Real GDP (chained 2017 dollars)

# FOMC meeting dates (approximate — updated based on Fed calendar)
FOMC_DATES_2026 = [
    '2026-01-28', '2026-01-29',  # January (no change expected)
    '2026-03-18', '2026-03-19',  # March
    '2026-05-06', '2026-05-07',  # May
    '2026-06-17', '2026-06-18',  # June
    '2026-07-29', '2026-07-30',  # July
    '2026-09-16', '2026-09-17',  # September
    '2026-11-04', '2026-11-05',  # November
    '2026-12-16', '2026-12-17',  # December
]


def _parse_fred_csv(series_id: str) -> list:
    """Fetch a FRED series and return list of (date_str, value) tuples."""
    try:
        r = requests.get(FRED_CSV, params={'id': series_id}, headers=HEADERS, timeout=15)
        r.raise_for_status()
        rows = []
        for line in r.text.strip().split('\n'):
            parts = line.split(',')
            if len(parts) == 2 and parts[0] != 'DATE':
                try:
                    rows.append((parts[0], float(parts[1])))
                except ValueError:
                    pass  # skip missing values (shown as '.')
        return rows
    except Exception as e:
        print(f'[EconClient] FRED {series_id} fetch error: {e}')
        return []


def _get_trend(values: list, n: int = 3) -> str:
    """Determine trend from last n values: up / down / flat."""
    if len(values) < 2:
        return 'unknown'
    recent = values[-n:]
    changes = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
    avg_change = sum(changes) / len(changes)
    if avg_change > 0.05:
        return 'up'
    elif avg_change < -0.05:
        return 'down'
    else:
        return 'flat'


def get_cpi_data() -> dict:
    """
    Fetch CPI-U data from BLS public API.
    Returns: latest value, MoM change, YoY change, trend, raw data.
    Falls back to FRED if BLS is slow.
    Cached for 1 hour to avoid BLS rate limits.
    """
    cached = _cache_get('cpi_data')
    if cached:
        return cached
    try:
        payload = {
            'seriesid': [CPI_SERIES],
            'startyear': str(datetime.now().year - 2),
            'endyear': str(datetime.now().year),
        }
        r = requests.post(f'{BLS_BASE}/', json=payload, headers=HEADERS, timeout=15)
        data = r.json()

        if data.get('status') != 'REQUEST_SUCCEEDED':
            raise ValueError(f"BLS error: {data.get('message', data.get('status'))}")

        series_data = data['Results']['series'][0]['data']
        # Sort chronologically (newest first from BLS)
        sorted_data = sorted(series_data,
            key=lambda x: (x['year'], x['period']), reverse=True)

        # Extract valid values
        valid = [(d['year'], d['period'], float(d['value']))
                 for d in sorted_data if d['value'] != '-']

        if not valid:
            raise ValueError("No valid CPI data")

        latest_val = valid[0][2]
        latest_year = valid[0][0]
        latest_period = valid[0][1]  # M01 - M12

        # MoM change
        mom_change = None
        if len(valid) >= 2:
            prev_val = valid[1][2]
            mom_change = round(((latest_val - prev_val) / prev_val) * 100, 3)

        # YoY change (12 months ago)
        yoy_change = None
        if len(valid) >= 13:
            year_ago_val = valid[12][2]
            yoy_change = round(((latest_val - year_ago_val) / year_ago_val) * 100, 2)

        # Trend
        values_list = [v[2] for v in reversed(valid[:12])]
        trend = _get_trend(values_list)

        result = {
            'source': 'BLS',
            'latest_value': latest_val,
            'latest_period': f"{latest_year}-{latest_period}",
            'mom_change_pct': mom_change,
            'yoy_change_pct': yoy_change,
            'trend': trend,
            'raw': valid[:13],  # last 13 months
            'fetched_at': datetime.utcnow().isoformat(),
        }
        _cache_set('cpi_data', result)
        return result

    except Exception as e:
        print(f'[EconClient] CPI BLS error: {e} — trying FRED fallback')
        # Fallback: FRED CPI-U (CPIAUCSL)
        cached_fallback = _cache_get('cpi_data_fred')
        if cached_fallback:
            return cached_fallback
        try:
            rows = _parse_fred_csv('CPIAUCSL')
            if not rows:
                return {'source': 'failed', 'error': str(e)}
            latest_val = rows[-1][1]
            mom_change = round(((rows[-1][1] - rows[-2][1]) / rows[-2][1]) * 100, 3) if len(rows) >= 2 else None
            yoy_change = round(((rows[-1][1] - rows[-13][1]) / rows[-13][1]) * 100, 2) if len(rows) >= 13 else None
            values_list = [r[1] for r in rows[-12:]]
            result = {
                'source': 'FRED_fallback',
                'latest_value': latest_val,
                'latest_period': rows[-1][0],
                'mom_change_pct': mom_change,
                'yoy_change_pct': yoy_change,
                'trend': _get_trend(values_list),
                'raw': rows[-13:],
                'fetched_at': datetime.utcnow().isoformat(),
            }
            _cache_set('cpi_data', result)
            _cache_set('cpi_data_fred', result)
            return result
        except Exception as e2:
            return {'source': 'failed', 'error': str(e2)}


def get_fed_rate() -> dict:
    """
    Fetch current Federal Funds Rate target range from FRED.
    Returns: current upper bound, effective rate, last change direction, next FOMC date.
    Cached for 1 hour.
    """
    cached = _cache_get('fed_rate')
    if cached:
        return cached
    try:
        # Target upper bound (daily, most precise)
        upper_rows = _parse_fred_csv(DFEDTARU_SERIES)
        # Effective rate (monthly avg)
        eff_rows = _parse_fred_csv(FEDFUNDS_SERIES)

        if not upper_rows:
            raise ValueError("No target rate data")

        current_upper = upper_rows[-1][1]
        current_eff = eff_rows[-1][1] if eff_rows else None

        # Detect last change
        last_change_dir = 'unchanged'
        last_change_amount = 0.0
        for i in range(len(upper_rows) - 1, 0, -1):
            diff = upper_rows[i][1] - upper_rows[i - 1][1]
            if abs(diff) > 0.001:
                last_change_dir = 'hike' if diff > 0 else 'cut'
                last_change_amount = round(diff, 3)
                break

        # Next FOMC date
        today_str = date.today().isoformat()
        next_fomc = None
        for d in sorted(FOMC_DATES_2026):
            if d >= today_str:
                next_fomc = d
                break

        result = {
            'source': 'FRED',
            'target_upper_bound': current_upper,
            'effective_rate': current_eff,
            'last_change_direction': last_change_dir,
            'last_change_amount_pct': last_change_amount,
            'next_fomc_date': next_fomc,
            'fetched_at': datetime.utcnow().isoformat(),
        }
        _cache_set('fed_rate', result)
        return result

    except Exception as e:
        print(f'[EconClient] Fed Rate error: {e}')
        return {'source': 'failed', 'error': str(e)}


def get_unemployment() -> dict:
    """
    Fetch US unemployment rate from FRED (UNRATE).
    Returns: latest rate, MoM change, trend.
    Cached for 1 hour.
    """
    cached = _cache_get('unemployment')
    if cached:
        return cached
    try:
        rows = _parse_fred_csv(UNRATE_SERIES)
        if not rows:
            raise ValueError("No unemployment data")

        latest_val = rows[-1][1]
        latest_date = rows[-1][0]
        mom_change = round(rows[-1][1] - rows[-2][1], 1) if len(rows) >= 2 else None
        yoy_change = round(rows[-1][1] - rows[-13][1], 1) if len(rows) >= 13 else None
        values_list = [r[1] for r in rows[-12:]]
        trend = _get_trend(values_list, n=3)

        result = {
            'source': 'FRED',
            'latest_rate': latest_val,
            'latest_date': latest_date,
            'mom_change_pp': mom_change,   # percentage points
            'yoy_change_pp': yoy_change,
            'trend': trend,
            'raw': rows[-13:],
            'fetched_at': datetime.utcnow().isoformat(),
        }
        _cache_set('unemployment', result)
        return result

    except Exception as e:
        print(f'[EconClient] Unemployment error: {e}')
        return {'source': 'failed', 'error': str(e)}


def get_gdp_data() -> dict:
    """
    Fetch Real GDP from FRED (GDPC1 — chained 2017 dollars).
    Returns: latest value, QoQ growth, trend.
    """
    try:
        rows = _parse_fred_csv(GDPC1_SERIES)
        if not rows:
            raise ValueError("No GDP data")

        latest_val = rows[-1][1]
        latest_date = rows[-1][0]
        qoq_pct = round(((rows[-1][1] - rows[-2][1]) / rows[-2][1]) * 100, 2) if len(rows) >= 2 else None
        yoy_pct = round(((rows[-1][1] - rows[-5][1]) / rows[-5][1]) * 100, 2) if len(rows) >= 5 else None
        values_list = [r[1] for r in rows[-6:]]
        trend = _get_trend(values_list, n=3)

        return {
            'source': 'FRED',
            'latest_value_billions': latest_val,
            'latest_quarter': latest_date,
            'qoq_growth_pct': qoq_pct,
            'yoy_growth_pct': yoy_pct,
            'trend': trend,
            'raw': rows[-6:],
            'fetched_at': datetime.utcnow().isoformat(),
        }

    except Exception as e:
        print(f'[EconClient] GDP error: {e}')
        return {'source': 'failed', 'error': str(e)}


def get_economic_signal(market_title: str, market_prob: float) -> dict:
    """
    Given a Kalshi market title and current YES probability (0-1),
    use BLS/FRED data to estimate model probability and compute edge.

    Args:
        market_title: e.g. "Will CPI rise more than 0.3% in March 2026?"
        market_prob: current YES price / 100 (e.g. 0.44 for 44¢)

    Returns:
        {model_prob, edge, confidence, signal_source, reasoning}
    """
    title_lower = market_title.lower()

    # ---- CPI Markets ----
    if 'cpi' in title_lower and ('rise more than' in title_lower or 'above' in title_lower):
        return _analyze_cpi_market(market_title, market_prob)

    # ---- Fed Rate Markets ----
    if 'federal funds rate' in title_lower or 'fed funds' in title_lower or 'upper bound' in title_lower:
        return _analyze_fed_market(market_title, market_prob)

    # ---- Unemployment Markets ----
    if 'unemployment' in title_lower:
        return _analyze_unemployment_market(market_title, market_prob)

    # ---- GDP Markets ----
    if 'gdp' in title_lower or 'gross domestic product' in title_lower:
        return _analyze_gdp_market(market_title, market_prob)

    return {
        'model_prob': None,
        'edge': None,
        'confidence': 'low',
        'signal_source': 'none',
        'reasoning': f'No matching economic indicator for: {market_title}',
    }


def _extract_threshold(title: str) -> float | None:
    """Extract numeric threshold from market title (e.g. 'more than 0.3%' → 0.3)."""
    patterns = [
        r'more than ([+-]?\d+\.?\d*)\s*%',
        r'above ([+-]?\d+\.?\d*)\s*%',
        r'exceed[s]?\s+([+-]?\d+\.?\d*)\s*%',
        r'([+-]?\d+\.?\d*)\s*%',
    ]
    for p in patterns:
        m = re.search(p, title, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def _analyze_cpi_market(market_title: str, market_prob: float) -> dict:
    """Analyze a CPI market using BLS data."""
    cpi = get_cpi_data()
    if cpi.get('source') == 'failed':
        return {
            'model_prob': market_prob,
            'edge': 0,
            'confidence': 'low',
            'signal_source': 'none',
            'reasoning': 'BLS/FRED data unavailable',
        }

    threshold = _extract_threshold(market_title)
    mom = cpi.get('mom_change_pct')
    yoy = cpi.get('yoy_change_pct')
    trend = cpi.get('trend', 'flat')

    if threshold is None or mom is None:
        return {
            'model_prob': None, 'edge': None,
            'confidence': 'low', 'signal_source': 'BLS',
            'reasoning': 'Could not parse threshold or missing CPI data',
        }

    # Naive model: use trend + last MoM reading to estimate probability
    # MoM CPI has been in 0.1-0.4% range recently
    # Model: if last reading was X, next reading will be within ±0.15pp with 60% confidence
    expected_mom = mom  # use last reading as baseline
    sigma = 0.12  # typical month-to-month standard deviation

    # P(CPI > threshold) using normal approximation
    from math import erf, sqrt
    z = (threshold - expected_mom) / (sigma * sqrt(2))
    model_prob = round(0.5 * (1 - erf(z)), 3)

    edge = round(model_prob - market_prob, 3)
    abs_edge = abs(edge)

    confidence = 'high' if abs_edge > 0.20 else 'medium' if abs_edge > 0.10 else 'low'

    return {
        'model_prob': model_prob,
        'edge': edge,
        'confidence': confidence,
        'signal_source': 'BLS_CPI',
        'reasoning': (
            f"Last CPI MoM: {mom:.3f}%. Threshold: {threshold}%. "
            f"Model P(>threshold): {model_prob:.1%} vs market: {market_prob:.1%}. "
            f"YoY: {yoy:.2f}%. Trend: {trend}."
        ),
    }


def _analyze_fed_market(market_title: str, market_prob: float) -> dict:
    """Analyze a Fed funds rate market using FRED data."""
    fed = get_fed_rate()
    if fed.get('source') == 'failed':
        return {
            'model_prob': market_prob, 'edge': 0,
            'confidence': 'low', 'signal_source': 'none',
            'reasoning': 'FRED data unavailable',
        }

    threshold = _extract_threshold(market_title)
    current_upper = fed.get('target_upper_bound', 3.75)
    next_fomc = fed.get('next_fomc_date')
    change_dir = fed.get('last_change_direction', 'unchanged')

    if threshold is None:
        return {
            'model_prob': None, 'edge': None,
            'confidence': 'low', 'signal_source': 'FRED',
            'reasoning': 'Could not parse threshold',
        }

    # For short-term markets: if threshold is below current rate, very high probability YES
    # If above current rate, depends on FOMC expectations
    if threshold < current_upper - 0.25:
        # Well below current — very likely YES
        model_prob = 0.95
    elif threshold < current_upper:
        # Just below current — high probability YES unless dramatic cut expected
        # Current rate is cutting, but slowly
        model_prob = 0.85 if change_dir == 'cut' else 0.92
    elif abs(threshold - current_upper) < 0.01:
        # Right at current rate — need to determine if market is for AT or ABOVE
        model_prob = 0.50
    elif threshold <= current_upper + 0.25:
        # One step above current — would require a hike
        model_prob = 0.08 if change_dir == 'cut' else 0.15
    else:
        # Well above current — very unlikely
        model_prob = 0.03

    edge = round(model_prob - market_prob, 3)

    return {
        'model_prob': model_prob,
        'edge': edge,
        'confidence': 'high' if abs(edge) > 0.15 else 'medium' if abs(edge) > 0.08 else 'low',
        'signal_source': 'FRED_FEDFUNDS',
        'reasoning': (
            f"Current upper bound: {current_upper}%. Threshold: {threshold}%. "
            f"Last change: {change_dir}. Next FOMC: {next_fomc}. "
            f"Model P(above threshold): {model_prob:.1%} vs market: {market_prob:.1%}."
        ),
    }


def _analyze_unemployment_market(market_title: str, market_prob: float) -> dict:
    """Analyze an unemployment rate market using FRED data."""
    unemp = get_unemployment()
    if unemp.get('source') == 'failed':
        return {
            'model_prob': market_prob, 'edge': 0,
            'confidence': 'low', 'signal_source': 'none',
            'reasoning': 'FRED data unavailable',
        }

    threshold = _extract_threshold(market_title)
    current_rate = unemp.get('latest_rate')
    mom = unemp.get('mom_change_pp', 0)
    trend = unemp.get('trend', 'flat')

    if threshold is None or current_rate is None:
        return {
            'model_prob': None, 'edge': None,
            'confidence': 'low', 'signal_source': 'FRED',
            'reasoning': 'Could not parse threshold or missing unemployment data',
        }

    # Unemployment tends to be sticky — next reading within ±0.2pp with high probability
    from math import erf, sqrt
    expected = current_rate + (mom * 0.5)  # dampen the trend
    sigma = 0.15  # typical std dev for unemployment MoM

    z = (threshold - expected) / (sigma * sqrt(2))
    model_prob = round(0.5 * (1 - erf(z)), 3)

    edge = round(model_prob - market_prob, 3)

    return {
        'model_prob': model_prob,
        'edge': edge,
        'confidence': 'high' if abs(edge) > 0.20 else 'medium' if abs(edge) > 0.10 else 'low',
        'signal_source': 'FRED_UNRATE',
        'reasoning': (
            f"Current unemployment: {current_rate}%. Threshold: {threshold}%. "
            f"MoM trend: {mom:+.1f}pp. Model P(above threshold): {model_prob:.1%} "
            f"vs market: {market_prob:.1%}. Trend: {trend}."
        ),
    }


def _analyze_gdp_market(market_title: str, market_prob: float) -> dict:
    """Analyze a GDP growth market using FRED data."""
    gdp = get_gdp_data()
    if gdp.get('source') == 'failed':
        return {
            'model_prob': market_prob, 'edge': 0,
            'confidence': 'low', 'signal_source': 'none',
            'reasoning': 'FRED data unavailable',
        }

    threshold = _extract_threshold(market_title)
    qoq = gdp.get('qoq_growth_pct', 0.35)
    trend = gdp.get('trend', 'flat')

    if threshold is None:
        return {
            'model_prob': None, 'edge': None,
            'confidence': 'low', 'signal_source': 'FRED',
            'reasoning': 'Could not parse threshold',
        }

    from math import erf, sqrt
    sigma = 0.5  # GDP QoQ is more volatile
    z = (threshold - qoq) / (sigma * sqrt(2))
    model_prob = round(0.5 * (1 - erf(z)), 3)
    edge = round(model_prob - market_prob, 3)

    return {
        'model_prob': model_prob,
        'edge': edge,
        'confidence': 'medium' if abs(edge) > 0.10 else 'low',
        'signal_source': 'FRED_GDP',
        'reasoning': (
            f"Last QoQ GDP growth: {qoq:.2f}%. Threshold: {threshold}%. "
            f"Model P(above threshold): {model_prob:.1%} vs market: {market_prob:.1%}. "
            f"Trend: {trend}."
        ),
    }


def get_upcoming_releases() -> list:
    """Return economic releases coming up in the next 30 days."""
    today = date.today()
    releases = [
        {'event': 'CPI', 'date': '2026-03-12', 'time_et': '08:30', 'series': 'KXCPI'},
        {'event': 'FOMC Meeting', 'date': '2026-03-18', 'time_et': '14:00', 'series': 'KXFED'},
        {'event': 'FOMC Meeting', 'date': '2026-03-19', 'time_et': '14:00', 'series': 'KXFED'},
        {'event': 'Unemployment', 'date': '2026-04-03', 'time_et': '08:30', 'series': 'KXECONSTATU3'},
        {'event': 'CPI', 'date': '2026-04-10', 'time_et': '08:30', 'series': 'KXCPI'},
    ]
    upcoming = []
    for r in releases:
        release_date = datetime.strptime(r['date'], '%Y-%m-%d').date()
        days_away = (release_date - today).days
        if 0 <= days_away <= 30:
            upcoming.append({**r, 'days_away': days_away})
    return upcoming


if __name__ == '__main__':
    print("=== Economics Client Test ===\n")

    print("--- CPI Data ---")
    cpi = get_cpi_data()
    print(f"  Source: {cpi.get('source')}")
    print(f"  Latest: {cpi.get('latest_value')} ({cpi.get('latest_period')})")
    print(f"  MoM: {cpi.get('mom_change_pct')}%")
    print(f"  YoY: {cpi.get('yoy_change_pct')}%")
    print(f"  Trend: {cpi.get('trend')}")

    print("\n--- Fed Rate ---")
    fed = get_fed_rate()
    print(f"  Upper bound: {fed.get('target_upper_bound')}%")
    print(f"  Effective: {fed.get('effective_rate')}%")
    print(f"  Last change: {fed.get('last_change_direction')} {fed.get('last_change_amount_pct')}%")
    print(f"  Next FOMC: {fed.get('next_fomc_date')}")

    print("\n--- Unemployment ---")
    unemp = get_unemployment()
    print(f"  Rate: {unemp.get('latest_rate')}%")
    print(f"  MoM: {unemp.get('mom_change_pp'):+.1f}pp")
    print(f"  Trend: {unemp.get('trend')}")

    print("\n--- GDP ---")
    gdp = get_gdp_data()
    print(f"  Latest: ${gdp.get('latest_value_billions'):.1f}B ({gdp.get('latest_quarter')})")
    print(f"  QoQ: {gdp.get('qoq_growth_pct')}%")
    print(f"  YoY: {gdp.get('yoy_growth_pct')}%")

    print("\n--- Signal Test: CPI Market ---")
    sig = get_economic_signal("Will CPI rise more than 0.3% in March 2026?", 0.44)
    print(f"  Model prob: {sig.get('model_prob'):.1%}" if sig.get('model_prob') else "  Model prob: N/A")
    print(f"  Edge: {sig.get('edge'):+.2f}" if sig.get('edge') is not None else "  Edge: N/A")
    print(f"  Confidence: {sig.get('confidence')}")
    print(f"  Reasoning: {sig.get('reasoning')}")

    print("\n--- Upcoming Releases ---")
    for rel in get_upcoming_releases():
        print(f"  {rel['event']} on {rel['date']} ({rel['days_away']}d away)")
