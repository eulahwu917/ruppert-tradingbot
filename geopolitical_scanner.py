"""
Geopolitical Market Scanner
Uses GDELT news signal + Kalshi market data to flag opportunities.
"""
import requests
import json
import os
from datetime import datetime, date
from logger import log_activity
from kalshi_market_search import find_series_by_keywords, get_markets_by_tickers

GEO_SEARCH_TERMS = [
    'ukraine', 'russia ceasefire', 'israel', 'iran nuclear', 'taiwan',
    'nato', 'china military', 'north korea', 'middle east',
    'sanctions', 'military', 'troops withdrawal', 'peace deal', 'war ends'
]

GEO_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'geopolitical_scout.jsonl')


def get_geo_markets():
    """Find geopolitical markets on Kalshi."""
    series = find_series_by_keywords(GEO_SEARCH_TERMS, limit=500)
    tickers = [s['ticker'] for s in series[:30]]
    markets = get_markets_by_tickers(tickers)
    log_activity(f"[Geo] Found {len(series)} geo series, {len(markets)} open markets")
    return markets


def get_gdelt_news_volume(query, timespan='24h'):
    """Get news article count from GDELT for a topic."""
    try:
        resp = requests.get(
            'https://api.gdeltproject.org/api/v2/doc/doc',
            params={
                'query': query,
                'mode': 'artlist',
                'maxrecords': 10,
                'timespan': timespan,
                'format': 'json',
                'sourcelang': 'english',
            },
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            articles = data.get('articles', [])
            return len(articles), [a.get('title', '') for a in articles[:2]]
    except Exception as e:
        pass
    return 0, []


def run_geo_scan():
    """Scan geopolitical markets with news signal analysis."""
    log_activity("[Geo] Scanning geopolitical markets...")
    markets = get_geo_markets()

    if not markets:
        log_activity("[Geo] No geopolitical markets found")
        return []

    flagged = []
    for m in markets[:15]:  # Limit API calls to GDELT
        title = m.get('title', '')
        yes_price = m.get('yes_ask', 0)
        if not yes_price:
            continue

        # Extract search terms from title (first 4 meaningful words)
        search_query = ' '.join([w for w in title.split() if len(w) > 3][:5])
        count, headlines = get_gdelt_news_volume(search_query)

        flagged.append({
            'ticker': m.get('ticker'),
            'title': title,
            'yes_price': yes_price,
            'market_prob': round(yes_price / 100, 2),
            'news_volume': count,
            'news_signal': 'HIGH' if count >= 5 else ('MEDIUM' if count >= 2 else 'LOW'),
            'recent_headlines': headlines,
            'requires_human_review': True,
        })

    # Sort by news volume
    flagged.sort(key=lambda x: x['news_volume'], reverse=True)

    # Log
    os.makedirs(os.path.dirname(GEO_LOG), exist_ok=True)
    with open(GEO_LOG, 'a', encoding='utf-8') as f:
        for item in flagged:
            f.write(json.dumps({'date': str(date.today()), **item}) + '\n')

    log_activity(f"[Geo] Flagged {len(flagged)} geopolitical markets")
    return flagged


def format_geo_brief(markets, max_show=5):
    """Format geopolitical brief for David's review."""
    if not markets:
        return "No geopolitical markets with news signal today."

    active = [m for m in markets if m['news_volume'] > 0]
    if not active:
        return f"Found {len(markets)} geopolitical markets but no active news signal."

    lines = [f"GEOPOLITICAL SCOUT -- {date.today().strftime('%b %d')}",
             "=" * 40,
             f"{len(active)} markets with news activity:\n"]

    for i, m in enumerate(active[:max_show], 1):
        title = (m['title'] or '').encode('ascii', 'replace').decode()
        lines.append(f"{i}. {title[:70]}")
        lines.append(f"   YES: {m['yes_price']}c ({m['market_prob']:.0%}) | News: {m['news_signal']} ({m['news_volume']} articles)")
        for h in m['recent_headlines'][:1]:
            headline = h.encode('ascii', 'replace').decode()
            lines.append(f"   Latest: {headline[:80]}")
        lines.append("")

    lines.append("Reply: number + BET YES/NO/PASS + size")
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    markets = run_geo_scan()
    brief = format_geo_brief(markets)
    print(brief)
