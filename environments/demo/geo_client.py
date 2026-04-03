"""
Geopolitical Data Client — TheNewsAPI + Polymarket + Kalshi market matcher.
Data-only module: no LLM calls. Returns structured event-market pairs.

Data sources:
  - TheNewsAPI (curated news feed, low latency)
  - Polymarket geo signals (market-implied probabilities)
  - Kalshi market search: finds geo-related prediction markets

Blending: TheNewsAPI 60% + Polymarket 40% (with fallback to sole source at 100%).

Output: list of dicts, each pairing a news event with a Kalshi market.
"""
import requests
import json
import os
from datetime import datetime, date, timezone
from agents.ruppert.data_scientist.logger import log_activity
from kalshi_market_search import find_series_by_keywords, get_markets_by_tickers

# ── Search terms for news + Kalshi discovery ─────────────────────────────────
GEO_SEARCH_TERMS = [
    'ukraine', 'russia ceasefire', 'israel', 'iran nuclear', 'taiwan',
    'nato', 'china military', 'north korea', 'middle east',
    'sanctions', 'military', 'troops withdrawal', 'peace deal', 'war ends',
]

# Keywords that map news articles to Kalshi market titles
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

# ── GDELT config ─────────────────────────────────────────────────────────────
_GDELT_DOC_BASE = 'https://api.gdeltproject.org/api/v2/doc/doc'
_GDELT_TIMEOUT = 15


class _GdeltRequestFailed(Exception):
    """Raised when GDELT API returns a non-retryable error (4xx/5xx)."""
    pass


def get_gdelt_events(query: str, timespan: str = '24h', max_records: int = 10) -> list[dict]:
    """
    Fetch recent news articles from GDELT DOC API for a keyword query.
    Returns list of dicts: [{url, title, seendate, domain, severity, event_type, country}]
    Raises _GdeltRequestFailed on non-retryable HTTP errors (429/5xx).
    Returns [] on network/parse errors (never raises those).
    """
    try:
        resp = requests.get(
            _GDELT_DOC_BASE,
            params={
                'query': query,
                'mode': 'artlist',
                'maxrecords': max_records,
                'format': 'json',
            },
            timeout=_GDELT_TIMEOUT,
        )
        if resp.status_code in (429, 500, 502, 503, 504):
            raise _GdeltRequestFailed(f"GDELT API error {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        articles = data.get('articles') or []
        result = []
        for art in articles:
            title = art.get('title', '')
            parsed = _parse_event(title)
            result.append({
                'url': art.get('url', ''),
                'title': title,
                'seendate': art.get('seendate', ''),
                'domain': art.get('domain', ''),
                'event_type': parsed['event_type'],
                'country': parsed['country'],
                'severity': parsed['severity'],
            })
        return result
    except _GdeltRequestFailed:
        raise
    except Exception as e:
        log_activity(f"[GeoClient] GDELT fetch error on '{query}': {e}")
        return []


# ── TheNewsAPI config ────────────────────────────────────────────────────────
_THENEWSAPI_KEY = 'RGPtfv3i6ni4bucrlfpUrMuDUMmRuvi9fGubxwmt'
_THENEWSAPI_BASE = 'https://api.thenewsapi.com/v1/news/all'
_THENEWSAPI_TIMEOUT = 10

# ── Blending weights ────────────────────────────────────────────────────────
W_NEWS = 0.60
W_POLY = 0.40


def get_thenewsapi_events(query: str, limit: int = 25) -> list[dict]:
    """
    Fetch recent news articles from TheNewsAPI for a geo keyword.
    Returns list of dicts: [{title, url, source, published_at, snippet, found_count}]
    Raises on non-retryable failure.
    """
    try:
        resp = requests.get(
            _THENEWSAPI_BASE,
            params={
                'api_token': _THENEWSAPI_KEY,
                'search': query,
                'language': 'en',
                'limit': limit,
            },
            timeout=_THENEWSAPI_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        found_count = data.get('meta', {}).get('found', 0)

        articles = []
        for art in data.get('data', []):
            title = art.get('title', '')
            parsed = _parse_event(title)
            articles.append({
                'title': title,
                'url': art.get('url', ''),
                'source': art.get('source', ''),
                'published_at': art.get('published_at', ''),
                'snippet': art.get('snippet', ''),
                'event_type': parsed['event_type'],
                'country': parsed['country'],
                'severity': parsed['severity'],
                'found_count': found_count,
            })
        return articles
    except Exception as e:
        log_activity(f"[GeoClient] TheNewsAPI fetch error on '{query}': {e}")
        raise


def get_all_news_events() -> list[dict]:
    """
    Fetch TheNewsAPI events across multiple geo search terms.
    Deduplicates by title. Returns [] on total failure.
    """
    seen_titles = set()
    all_events = []

    for term in GEO_SEARCH_TERMS:
        try:
            events = get_thenewsapi_events(query=term, limit=10)
            for ev in events:
                title_key = ev['title'].lower().strip()
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_events.append(ev)
        except Exception as e:
            log_activity(f"[GeoClient] TheNewsAPI query '{term}' failed: {e}")

    all_events.sort(key=lambda x: x['severity'], reverse=True)
    return all_events


def _news_volume_score(events: list[dict]) -> float:
    """
    Compute a 0-1 volume score from TheNewsAPI found counts.
    Higher found_count → more articles → higher geo activity signal.
    """
    if not events:
        return 0.0
    total_found = sum(ev.get('found_count', 0) for ev in events)
    # Normalize: 100+ articles across terms → 1.0
    return min(1.0, total_found / 100.0)


def _polymarket_severity_score(poly_signals: list[dict]) -> float:
    """
    Compute a 0-1 severity score from Polymarket geo signals.
    Uses average yes_price weighted by volume_24h.
    """
    if not poly_signals:
        return 0.0
    total_vol = sum(s.get('volume_24h', 0) for s in poly_signals)
    if total_vol <= 0:
        # Equal-weight average
        prices = [s.get('yes_price', 0) for s in poly_signals if s.get('yes_price') is not None]
        return sum(prices) / len(prices) if prices else 0.0
    weighted_sum = sum(
        (s.get('yes_price', 0) or 0) * s.get('volume_24h', 0)
        for s in poly_signals
    )
    return min(1.0, weighted_sum / total_vol)


def get_blended_severity() -> tuple[float, str]:
    """
    Compute blended severity from TheNewsAPI + Polymarket.
    Returns (severity_score, source_description).
    Fallback: if one source fails, use the other at 100%.
    If both fail, returns (0.0, 'no_signal').
    """
    news_score = None
    poly_score = None

    # TheNewsAPI
    try:
        news_events = get_all_news_events()
        if news_events:
            news_score = _news_volume_score(news_events)
    except Exception as e:
        log_activity(f"[GeoClient] TheNewsAPI total failure: {e}")

    # Polymarket
    try:
        from agents.ruppert.data_analyst.polymarket_client import get_geo_signals
        poly_signals = get_geo_signals()
        if poly_signals:
            poly_score = _polymarket_severity_score(poly_signals)
    except Exception as e:
        log_activity(f"[GeoClient] Polymarket geo signals failed: {e}")

    # Blend with fallback
    if news_score is not None and poly_score is not None:
        blended = W_NEWS * news_score + W_POLY * poly_score
        source = f'thenewsapi({news_score:.2f})x{W_NEWS}+polymarket({poly_score:.2f})x{W_POLY}'
    elif news_score is not None:
        blended = news_score
        source = f'thenewsapi_only({news_score:.2f})'
        log_activity("[GeoClient] Polymarket unavailable — using TheNewsAPI at 100%")
    elif poly_score is not None:
        blended = poly_score
        source = f'polymarket_only({poly_score:.2f})'
        log_activity("[GeoClient] TheNewsAPI unavailable — using Polymarket at 100%")
    else:
        log_activity("[GeoClient] Both sources failed — no geo signal")
        return 0.0, 'no_signal'

    return round(blended, 4), source


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
    Check if a news event is relevant to a Kalshi market by title keyword matching.
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
    Main entry point: fetch news events via TheNewsAPI + Polymarket,
    find matching Kalshi markets, return structured list of event-market pairs.

    Returns: [{
        event: {title, url, source, event_type, country, severity},
        market_title: str,
        market_ticker: str,
        current_price: int (yes_ask in cents),
        days_to_expiry: float,
        match_score: int,
        blended_severity: float,
        severity_source: str,
    }]

    NEVER raises — returns [] on any failure so the cycle continues.
    """
    try:
        return _get_events_inner()
    except Exception as e:
        log_activity(f"[GeoClient] Unhandled error in get_events — returning empty: {e}")
        return []


def _get_events_inner():
    """Inner implementation of get_events (may raise)."""
    # Fetch blended severity score
    blended_sev, sev_source = get_blended_severity()

    # Fetch news events for market matching
    events = get_all_news_events()
    if not events:
        log_activity("[GeoClient] No news events found")
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
                'blended_severity': blended_sev,
                'severity_source': sev_source,
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

    log_activity(f"[GeoClient] {len(events)} events, {len(markets)} markets, {len(deduped)} pairs | severity={blended_sev:.3f} ({sev_source})")
    return deduped


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=== TheNewsAPI Event Fetch ===")
    events = get_all_news_events()
    print(f"Found {len(events)} events")
    for ev in events[:5]:
        print(f"  [{ev['severity']}] {ev['event_type']:12} {ev['country']:12} {ev['title'][:70]}")

    print("\n=== Blended Severity ===")
    sev, src = get_blended_severity()
    print(f"  Score: {sev:.3f} ({src})")

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
