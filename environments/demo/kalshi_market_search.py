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


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("\n=== TECH/GAMING SERIES ===")
    tech = find_series_by_keywords(['apple', 'openai', 'microsoft', 'gaming', 'xbox', 'playstation', 'nintendo', 'game release', 'gta', 'activision'])
    for s in tech[:20]:
        title = (s.get('title') or '').encode('ascii', 'replace').decode()
        print(f"  [{s['ticker']}] {title[:70]}")

