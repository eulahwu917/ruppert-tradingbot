"""
Geopolitical Data Client — GDELT event feed + Kalshi market matcher.
Data-only module: no LLM calls. Returns structured event-market pairs.

Data sources:
  - GDELT v2 DOC API (free, ~15 min refresh): recent geopolitical news articles
  - Kalshi market search: finds geo-related prediction markets

Output: list of dicts, each pairing a GDELT event with a Kalshi market.
"""
import requests
import json
import os
import time
from datetime import datetime, date, timezone
from agents.data_scientist.logger import log_activity
from kalshi_market_search import find_series_by_keywords, get_markets_by_tickers

# ── Search terms for GDELT + Kalshi discovery ────────────────────────────────
GEO_SEARCH_TERMS = [
    'ukraine', 'russia ceasefire', 'israel', 'iran nuclear', 'taiwan',
    'nato', 'china military', 'north korea', 'middle east',
    'sanctions', 'military', 'troops withdrawal', 'peace deal', 'war ends',
]

# Keywords that map GDELT articles to Kalshi market titles
MATCH_KEYWORDS = {
    'ukraine':    ['ukraine', 'kyiv', 'zelensky'],
    'russia':     ['russia', 'putin', 'moscow', 'kremlin'],
    'ceasefire':  ['ceasefire', 'peace deal', 'truce', 'armistice'],
    'israel':     ['israel', 'gaza', 'hamas', 'netanyahu', 'idf'],
    'iran':       ['iran', 'nuclear', 'tehran', 'irgc'],
    'taiwan':     ['taiwan', 'taipei', 'strait'],
    'china':      ['china', 'beijing', 'xi jinping', 'pla'],
    'nato':       ['nato', 'alliance', 'article 5'],
    'north korea': ['north korea', 'pyongyang', 'kim jong'],
    'sanctions':  ['sanctions', 'embargo', 'tariff'],
    'troops':     ['troops', 'military', 'deployment', 'withdrawal'],
}

GEO_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'geo_client.jsonl')

# ── Rate-limiting / resilience constants ─────────────────────────────────────
_GDELT_TIMEOUT = 8            # seconds per request (was 15)
_MAX_RETRIES = 3              # retries per query on 429
_CIRCUIT_BREAKER_LIMIT = 3    # consecutive failures before tripping
_TIME_BUDGET_SECONDS = 180    # 3-minute total budget for geo scan


def get_gdelt_events(query='geopolitical conflict', timespan='24h', max_records=25):
    """
    Fetch recent geopolitical articles from GDELT v2 DOC API.
    Retries with exponential backoff on 429 responses.

    Returns list of dicts: [{title, url, source, seendate, domain, event_type, country, severity}]
    Raises _GdeltRequestFailed on non-retryable failure (for circuit breaker tracking).
    """
    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                'https://api.gdeltproject.org/api/v2/doc/doc',
                params={
                    'query': query,
                    'mode': 'artlist',
                    'maxrecords': max_records,
                    'timespan': timespan,
                    'format': 'json',
                    'sourcelang': 'english',
                },
                timeout=_GDELT_TIMEOUT
            )
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                log_activity(f"[GeoClient] GDELT 429 on '{query}', backoff {wait}s (attempt {attempt+1}/{_MAX_RETRIES})")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                log_activity(f"[GeoClient] GDELT returned {resp.status_code} for '{query}'")
                raise _GdeltRequestFailed(f"HTTP {resp.status_code}")

            data = resp.json()
            articles = data.get('articles', [])

            events = []
            for art in articles:
                title = art.get('title', '')
                parsed = _parse_event(title)
                events.append({
                    'title': title,
                    'url': art.get('url', ''),
                    'source': art.get('domain', ''),
                    'seendate': art.get('seendate', ''),
                    'event_type': parsed['event_type'],
                    'country': parsed['country'],
                    'severity': parsed['severity'],
                })

            return events

        except _GdeltRequestFailed:
            raise
        except requests.exceptions.Timeout:
            log_activity(f"[GeoClient] GDELT timeout on '{query}' (attempt {attempt+1}/{_MAX_RETRIES})")
            last_err = "timeout"
            continue
        except Exception as e:
            log_activity(f"[GeoClient] GDELT fetch error on '{query}': {e}")
            raise _GdeltRequestFailed(str(e))

    # Exhausted retries (429s or timeouts)
    log_activity(f"[GeoClient] GDELT exhausted {_MAX_RETRIES} retries for '{query}' (last: {last_err})")
    raise _GdeltRequestFailed(f"exhausted retries for '{query}'")


class _GdeltRequestFailed(Exception):
    """Internal signal for circuit breaker tracking."""
    pass


def get_all_gdelt_events(timespan='24h'):
    """
    Fetch GDELT events across multiple geo search terms.
    Deduplicates by title. Includes circuit breaker and time budget.
    """
    seen_titles = set()
    all_events = []
    consecutive_failures = 0
    start_time = time.monotonic()

    for term in GEO_SEARCH_TERMS:
        # Time budget check
        elapsed = time.monotonic() - start_time
        if elapsed > _TIME_BUDGET_SECONDS:
            log_activity("[GeoClient] Time budget exceeded — aborting geo scan")
            break

        # Circuit breaker check
        if consecutive_failures >= _CIRCUIT_BREAKER_LIMIT:
            log_activity("[GeoClient] GDELT circuit breaker triggered — skipping remaining queries this cycle")
            break

        try:
            events = get_gdelt_events(query=term, timespan=timespan, max_records=10)
            consecutive_failures = 0  # reset on success
            for ev in events:
                title_key = ev['title'].lower().strip()
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_events.append(ev)
        except _GdeltRequestFailed as e:
            log_activity(f"[GeoClient] Query '{term}' failed: {e}")
            consecutive_failures += 1

    # Sort by severity descending
    all_events.sort(key=lambda x: x['severity'], reverse=True)
    return all_events


def _parse_event(title):
    """
    Extract event type, country, and severity indicators from a headline.
    Simple keyword-based parser (no LLM).
    """
    title_lower = title.lower()

    # Detect event type
    event_type = 'unknown'
    type_keywords = {
        'conflict':   ['attack', 'strike', 'bomb', 'war', 'combat', 'offensive', 'invasion', 'clash'],
        'diplomacy':  ['talks', 'summit', 'negotiate', 'deal', 'agreement', 'treaty', 'diplomat'],
        'ceasefire':  ['ceasefire', 'truce', 'peace', 'armistice', 'halt'],
        'sanctions':  ['sanction', 'embargo', 'tariff', 'ban', 'restrict'],
        'military':   ['troops', 'deploy', 'military', 'defense', 'weapons', 'missile', 'nuclear'],
        'election':   ['election', 'vote', 'referendum', 'ballot'],
    }
    for etype, keywords in type_keywords.items():
        if any(kw in title_lower for kw in keywords):
            event_type = etype
            break

    # Detect country/region
    country = 'unknown'
    country_keywords = {
        'Ukraine':     ['ukraine', 'kyiv', 'zelensky'],
        'Russia':      ['russia', 'putin', 'moscow', 'kremlin'],
        'Israel':      ['israel', 'gaza', 'hamas', 'netanyahu'],
        'Iran':        ['iran', 'tehran'],
        'Taiwan':      ['taiwan', 'taipei'],
        'China':       ['china', 'beijing', 'xi jinping'],
        'North Korea': ['north korea', 'pyongyang', 'kim jong'],
        'Middle East': ['middle east', 'gulf', 'saudi', 'yemen'],
    }
    for cname, keywords in country_keywords.items():
        if any(kw in title_lower for kw in keywords):
            country = cname
            break

    # Severity heuristic (1-5)
    severity = 1
    high_sev = ['war', 'invasion', 'nuclear', 'attack', 'strike', 'bomb', 'missile', 'kill']
    med_sev = ['troops', 'deploy', 'sanction', 'military', 'conflict', 'escalat', 'threat']
    low_sev = ['talks', 'diplomat', 'summit', 'negotiate', 'peace']

    if any(kw in title_lower for kw in high_sev):
        severity = 4
    elif any(kw in title_lower for kw in med_sev):
        severity = 3
    elif any(kw in title_lower for kw in low_sev):
        severity = 2

    # Boost severity if multiple high-signal words
    high_count = sum(1 for kw in high_sev if kw in title_lower)
    if high_count >= 2:
        severity = 5

    return {'event_type': event_type, 'country': country, 'severity': severity}


def get_geo_markets():
    """Find geopolitical markets on Kalshi via series search."""
    series = find_series_by_keywords(GEO_SEARCH_TERMS, limit=500)
    tickers = [s['ticker'] for s in series[:30]]
    markets = get_markets_by_tickers(tickers)
    log_activity(f"[GeoClient] Found {len(series)} geo series, {len(markets)} open markets")
    return markets


def _match_event_to_market(event, market):
    """
    Check if a GDELT event is relevant to a Kalshi market by title keyword matching.
    Returns a relevance score (0 = no match, higher = stronger match).
    """
    ev_title = event.get('title', '').lower()
    mkt_title = (market.get('title', '') or '').lower()

    score = 0
    for category, keywords in MATCH_KEYWORDS.items():
        ev_hits = sum(1 for kw in keywords if kw in ev_title)
        mkt_hits = sum(1 for kw in keywords if kw in mkt_title)
        if ev_hits > 0 and mkt_hits > 0:
            score += ev_hits + mkt_hits

    return score


def _days_to_expiry(market):
    """Calculate days until market closes. Returns float or None."""
    close_time = market.get('close_time', '')
    if not close_time:
        return None
    try:
        ct = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
        delta = ct - datetime.now(timezone.utc)
        return max(0, delta.total_seconds() / 86400)
    except Exception:
        return None


def get_events(timespan='24h'):
    """
    Main entry point: fetch GDELT events, find matching Kalshi markets,
    return structured list of event-market pairs.

    Returns: [{
        event: {title, url, source, event_type, country, severity},
        market_title: str,
        market_ticker: str,
        current_price: int (yes_ask in cents),
        days_to_expiry: float,
        match_score: int,
    }]

    NEVER raises — returns [] on any failure so the cycle continues.
    """
    try:
        return _get_events_inner(timespan=timespan)
    except Exception as e:
        log_activity(f"[GeoClient] Unhandled error in get_events — returning empty: {e}")
        return []


def _get_events_inner(timespan='24h'):
    """Inner implementation of get_events (may raise)."""
    events = get_all_gdelt_events(timespan=timespan)
    if not events:
        log_activity("[GeoClient] No GDELT events found")
        return []

    markets = get_geo_markets()
    if not markets:
        log_activity("[GeoClient] No geo markets found on Kalshi")
        return []

    # Match events to markets
    pairs = []
    for event in events:
        for market in markets:
            score = _match_event_to_market(event, market)
            if score <= 0:
                continue

            yes_ask = market.get('yes_ask', 0) or 0
            if yes_ask <= 0:
                continue

            days = _days_to_expiry(market)

            pairs.append({
                'event': {
                    'title': event['title'],
                    'url': event.get('url', ''),
                    'source': event.get('source', ''),
                    'event_type': event['event_type'],
                    'country': event['country'],
                    'severity': event['severity'],
                },
                'market_title': market.get('title', ''),
                'market_ticker': market.get('ticker', ''),
                'current_price': yes_ask,
                'days_to_expiry': round(days, 2) if days is not None else None,
                'match_score': score,
                'no_ask': market.get('no_ask', 0) or 0,
                'yes_bid': market.get('yes_bid', 0) or 0,
            })

    # Sort by match score * event severity (best pairs first)
    pairs.sort(key=lambda x: x['match_score'] * x['event']['severity'], reverse=True)

    # Deduplicate: keep best pair per market ticker
    seen_tickers = set()
    deduped = []
    for p in pairs:
        ticker = p['market_ticker']
        if ticker not in seen_tickers:
            seen_tickers.add(ticker)
            deduped.append(p)

    # Log
    os.makedirs(os.path.dirname(GEO_LOG), exist_ok=True)
    with open(GEO_LOG, 'a', encoding='utf-8') as f:
        for item in deduped:
            f.write(json.dumps({'date': str(date.today()), **item}) + '\n')

    log_activity(f"[GeoClient] {len(events)} events, {len(markets)} markets, {len(deduped)} pairs matched")
    return deduped


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=== GDELT Event Fetch ===")
    events = get_all_gdelt_events(timespan='24h')
    print(f"Found {len(events)} events")
    for ev in events[:5]:
        print(f"  [{ev['severity']}] {ev['event_type']:12} {ev['country']:12} {ev['title'][:70]}")

    print("\n=== Kalshi Geo Markets ===")
    markets = get_geo_markets()
    print(f"Found {len(markets)} markets")
    for m in markets[:5]:
        print(f"  {m.get('ticker', '?'):30} YES={m.get('yes_ask', '?')}c  {(m.get('title', '') or '')[:60]}")

    print("\n=== Event-Market Pairs ===")
    pairs = get_events(timespan='24h')
    print(f"Matched {len(pairs)} pairs")
    for p in pairs[:10]:
        ev = p['event']
        print(f"  [{ev['severity']}] {ev['title'][:50]:50} -> {p['market_ticker']:25} YES={p['current_price']}c")
