"""
Kalshi Market Search Utilities
Centralized helpers for fetching markets by category/series.
"""
import requests

API_BASE = 'https://api.elections.kalshi.com/trade-api/v2'


def get_events_by_category(category, limit=100):
    """Fetch events by category string."""
    try:
        resp = requests.get(f'{API_BASE}/events', params={'limit': limit, 'status': 'open'}, timeout=15)
        resp.raise_for_status()
        events = resp.json().get('events', [])
        return [e for e in events if (e.get('category') or '').lower() == category.lower()]
    except Exception as e:
        print(f"[Search] Error: {e}")
        return []


def search_series(query, limit=200):
    """Search series by title keyword."""
    try:
        resp = requests.get(f'{API_BASE}/series', params={'limit': limit}, timeout=15)
        resp.raise_for_status()
        series = resp.json().get('series', [])
        query_lower = query.lower()
        return [s for s in series if query_lower in (s.get('title') or '').lower()]
    except Exception as e:
        print(f"[Search] Series error: {e}")
        return []


def get_markets_for_series(series_ticker):
    """Get open markets for a specific series ticker."""
    try:
        resp = requests.get(
            f'{API_BASE}/markets',
            params={'series_ticker': series_ticker, 'status': 'open', 'limit': 20},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json().get('markets', [])
    except Exception as e:
        print(f"[Search] Markets error for {series_ticker}: {e}")
        return []


def get_markets_by_tickers(series_tickers):
    """Get open markets for a list of series tickers."""
    all_markets = []
    for ticker in series_tickers:
        markets = get_markets_for_series(ticker)
        all_markets.extend(markets)
    return all_markets


# Known series tickers by category
ECONOMICS_SERIES = [
    'KXCPI', 'KXCORECPI', 'KXUNRATE', 'KXFOMC', 'KXFEDRATE',
    'KXNFP', 'KXGDP', 'KXPCE', 'KXSPX', 'KXNDX',
    'KXRECESSION', 'KXMORTGAGE', 'KXGAS',
]

GEOPOLITICAL_SERIES = [
    'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
    'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
]

TECH_GAMING_SERIES = [
    'KXAAPLWATCH', 'KXOAIANTH', 'KXRAMPBREX', 'KXDEELRIP',
]


def find_series_by_keywords(keywords, limit=500):
    """Find series tickers matching any of the given keywords in title."""
    try:
        resp = requests.get(f'{API_BASE}/series', params={'limit': limit}, timeout=15)
        resp.raise_for_status()
        all_series = resp.json().get('series', [])
        matches = []
        for s in all_series:
            title = (s.get('title') or '').lower()
            if any(kw in title for kw in keywords):
                matches.append(s)
        return matches
    except Exception as e:
        print(f"[Search] Error: {e}")
        return []


GEO_TITLE_KEYWORDS = [
    'war', 'election', 'president', 'congress', 'sanction', 'trade',
    'nato', 'china', 'russia', 'iran', 'nuclear', 'ukraine', 'israel',
    'ceasefire', 'taiwan', 'military', 'troops', 'invasion',
]


def search_geo_markets(kalshi_client, max_markets=50):
    """
    Fetch open geo/political markets via KalshiClient.
    1. Pull from known GEOPOLITICAL_SERIES via KalshiClient.get_markets()
    2. Also discover series by keyword search and fetch those too
    3. Deduplicate, filter to open markets with orderbook data
    Returns up to max_markets market dicts with live yes_ask/yes_bid prices.
    """
    from logger import log_activity
    seen_tickers = set()
    all_markets = []

    # Step 1: fetch from known geo series
    for series_ticker in GEOPOLITICAL_SERIES:
        try:
            markets = kalshi_client.get_markets(series_ticker, status='open', limit=30)
            for m in markets:
                ticker = m.get('ticker', '')
                if ticker and ticker not in seen_tickers:
                    seen_tickers.add(ticker)
                    all_markets.append(m)
        except Exception as e:
            log_activity(f"[GeoSearch] Error fetching {series_ticker}: {e}")
        if len(all_markets) >= max_markets:
            break

    # Step 2: discover additional series by keyword search
    if len(all_markets) < max_markets:
        try:
            discovered = find_series_by_keywords(GEO_TITLE_KEYWORDS, limit=500)
            # Filter out series we already fetched
            known_set = set(GEOPOLITICAL_SERIES)
            new_series = [s for s in discovered if s['ticker'] not in known_set]
            for s in new_series[:20]:
                try:
                    markets = kalshi_client.get_markets(s['ticker'], status='open', limit=20)
                    for m in markets:
                        ticker = m.get('ticker', '')
                        title_lower = (m.get('title') or '').lower()
                        # Only include if title contains a geo keyword
                        if ticker and ticker not in seen_tickers and any(kw in title_lower for kw in GEO_TITLE_KEYWORDS):
                            seen_tickers.add(ticker)
                            all_markets.append(m)
                except Exception as e:
                    log_activity(f"[GeoSearch] Error fetching discovered series {s['ticker']}: {e}")
                if len(all_markets) >= max_markets:
                    break
        except Exception as e:
            log_activity(f"[GeoSearch] Keyword discovery error: {e}")

    log_activity(f"[GeoSearch] Found {len(all_markets)} open geo markets")
    return all_markets[:max_markets]


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=== ECONOMICS SERIES ===")
    econ = find_series_by_keywords(['cpi', 'inflation', 'fed rate', 'fomc', 'unemployment', 'gdp', 'payroll', 'recession', 'interest rate'])
    for s in econ[:20]:
        title = (s.get('title') or '').encode('ascii', 'replace').decode()
        print(f"  [{s['ticker']}] {title[:70]}")

    print("\n=== TECH/GAMING SERIES ===")
    tech = find_series_by_keywords(['apple', 'openai', 'microsoft', 'gaming', 'xbox', 'playstation', 'nintendo', 'game release', 'gta', 'activision'])
    for s in tech[:20]:
        title = (s.get('title') or '').encode('ascii', 'replace').decode()
        print(f"  [{s['ticker']}] {title[:70]}")

    print("\n=== GEOPOLITICAL SERIES ===")
    geo = find_series_by_keywords(['ukraine', 'russia', 'ceasefire', 'israel', 'iran', 'taiwan', 'china', 'war', 'nato'])
    for s in geo[:20]:
        title = (s.get('title') or '').encode('ascii', 'replace').decode()
        print(f"  [{s['ticker']}] {title[:70]}")
