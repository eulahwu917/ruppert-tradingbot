"""
Gaming & Tech Scout Module
Scans Kalshi for gaming/tech/entertainment markets David has edge on.
"""
import requests
import json
import os
from datetime import datetime, date
from logger import log_activity
from kalshi_market_search import get_markets_by_tickers, find_series_by_keywords

# Known gaming/tech series tickers
GAMING_TECH_SERIES = [
    'KXGTA6',           # GTA 6 release date
    'KXGTA6ONTIME',     # GTA 6 on time
    'KXAPPLEFOLD',      # Apple foldable iPhone
    'KXAAPLPRICE17OVER16', # iPhone 17 price
    'KXOAIPROFIT',      # OpenAI for-profit
    'KXOAIANTH',        # OpenAI or Anthropic IPO first
    'KXRAMPBREX',       # Ramp or Brex IPO
    'KXDEELRIP',        # Deel or Rippling IPO
    'KXAPPSTOREVISIONGAME', # Apple Vision Pro GOTY
    'OAIAGI',           # OpenAI achieves AGI
    'APPLEAI',          # Apple AI partnership
    'KXPAIDSUBAPPLEINTEL',  # Apple Intelligence
]

GAMING_SEARCH_TERMS = [
    'gta', 'grand theft auto', 'xbox', 'playstation', 'nintendo', 'activision',
    'blizzard', 'game release', 'game award', 'steam', 'game pass',
    'openai', 'anthropic', 'microsoft acquire', 'esport', 'streaming service',
    'netflix subscribers', 'disney plus', 'oscar award', 'emmy award',
    'grammy award', 'box office', 'spotify wrapped', 'apple event',
    'apple intelligence', 'apple vision', 'iphone release', 'iphone price',
    'video game', 'game studio', 'game developer'
]

# Explicit sports exclusions — anything matching these is NOT gaming/tech
SPORTS_EXCLUSIONS = [
    'points scored', 'rebounds', 'assists', 'touchdowns', 'home runs',
    'field goal', 'three-pointer', 'wins by', 'over 1', 'over 2', 'over 3',
    'over 1.5', 'over 2.5', 'lakers', 'celtics', 'warriors', 'knicks',
    'heat', 'bulls', 'nets', 'nba', 'nfl', 'mlb', 'nhl', 'mls', 'ncaa',
    'soccer', 'basketball game', 'football game', 'baseball game', 'hockey game',
    'tennis match', 'golf tournament', 'mma fight', 'boxing match',
    'both teams to score', 'goals scored', 'rushing yards', 'passing yards',
    'strikeouts', 'innings', 'shots on goal', 'power play', 'penalty kick',
    'first quarter', 'second half', 'overtime', 'series wins', 'championship win',
    'super bowl', 'world series', 'nba finals', 'stanley cup', 'world cup'
]

SCOUT_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'gaming_scout.jsonl')


def get_gaming_markets():
    """Fetch gaming/tech markets using series tickers + keyword search."""
    # Known series
    known_markets = get_markets_by_tickers(GAMING_TECH_SERIES)

    # Dynamic discovery
    series = find_series_by_keywords(GAMING_SEARCH_TERMS, limit=500)
    dynamic_tickers = [s['ticker'] for s in series[:30]]
    dynamic_markets = get_markets_by_tickers(dynamic_tickers)

    # Combine, deduplicate by ticker
    all_markets = {m['ticker']: m for m in known_markets + dynamic_markets}

    # Filter out sports markets
    filtered = {}
    for ticker, m in all_markets.items():
        title = (m.get('title') or '').lower()
        if not any(excl in title for excl in SPORTS_EXCLUSIONS):
            filtered[ticker] = m

    return list(filtered.values())


def ruppert_analysis(market):
    """Ruppert's analysis — flags patterns, David adds real intel."""
    title = (market.get('title') or '').lower()
    yes_price = market.get('yes_ask', 50)
    prob = yes_price / 100 if yes_price else 0.5

    notes = []
    if prob > 0.85:
        notes.append("Near-certain YES — only bet NO if you know something")
    elif prob < 0.15:
        notes.append("Near-certain NO — only bet YES if you know something")
    elif 0.35 < prob < 0.65:
        notes.append("50/50 — market uncertain, insider knowledge has max edge")

    if any(kw in title for kw in ['release', 'launch', 'ship', 'date']):
        notes.append("Release date market — do you have timing intel?")
    if any(kw in title for kw in ['acqui', 'merger', 'buy', 'purchase']):
        notes.append("Acquisition market — your network is the edge")
    if 'gta' in title or 'grand theft' in title:
        notes.append("GTA market — Take-Two history of delays is relevant")
    if 'openai' in title or 'anthropic' in title or 'ipo' in title.lower():
        notes.append("AI/IPO market — tech industry signals matter here")

    return notes


def run_daily_scout():
    """Run the daily gaming/tech scout."""
    log_activity("[Scout] Running daily gaming/tech scan...")
    markets = get_gaming_markets()
    log_activity(f"[Scout] Found {len(markets)} gaming/tech markets")

    scouted = []
    for m in markets:
        notes = ruppert_analysis(m)
        yes_price = m.get('yes_ask', 0)
        scouted.append({
            'ticker': m.get('ticker'),
            'title': m.get('title'),
            'yes_price': yes_price,
            'market_prob': round(yes_price / 100, 2) if yes_price else None,
            'close_date': (m.get('close_time') or '')[:10],
            'ruppert_notes': notes,
            'scanned_at': datetime.now().isoformat(),
        })

    # Sort: most uncertain (near 50/50) first
    scouted.sort(key=lambda x: abs((x['market_prob'] or 0.5) - 0.5))

    # Log
    os.makedirs(os.path.dirname(SCOUT_LOG), exist_ok=True)
    with open(SCOUT_LOG, 'a', encoding='utf-8') as f:
        for m in scouted:
            f.write(json.dumps({'date': str(date.today()), **m}) + '\n')

    return scouted


def format_scout_brief(markets, max_show=8):
    """Format the daily scout brief."""
    if not markets:
        return "No gaming/tech markets found today."

    lines = [f"GAMING/TECH SCOUT -- {date.today().strftime('%b %d')}",
             "=" * 40,
             f"{len(markets)} markets found. Top {min(max_show, len(markets))}:\n"]

    for i, m in enumerate(markets[:max_show], 1):
        title = (m['title'] or '').encode('ascii', 'replace').decode()
        prob_str = f"{m['market_prob']:.0%}" if m['market_prob'] else "?"
        close_str = f" | closes {m['close_date']}" if m['close_date'] else ""
        lines.append(f"{i}. {title[:70]}")
        lines.append(f"   YES: {m['yes_price']}c ({prob_str}){close_str}")
        for note in m['ruppert_notes']:
            lines.append(f"   >> {note}")
        lines.append("")

    lines.append("Reply with number + your view to flag for trading.")
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    markets = run_daily_scout()
    brief = format_scout_brief(markets)
    print(brief)
