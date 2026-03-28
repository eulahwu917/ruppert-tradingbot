"""
Geopolitical Market Scanner — Market-First Design
1. Fetch open Kalshi geo/political markets (with real prices via KalshiClient)
2. For each market, query GDELT for news relevant to THAT specific question
3. Stage 1 (Haiku): is there relevant news with severity >= 3?
4. Stage 2 (Sonnet): given the news, what probability does the market resolve YES?
5. Compare Sonnet estimate vs market price -> enter if edge exists
"""
import json
import os
import re
import time
from datetime import datetime, date, timezone
from agents.data_scientist.logger import log_activity
from agents.data_analyst.kalshi_client import KalshiClient
from kalshi_market_search import search_geo_markets
from geo_client import get_gdelt_events, _days_to_expiry, _GdeltRequestFailed
from geo_edge_detector import stage1_classify, stage2_estimate
import config as cfg

GEO_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'geopolitical_scanner.jsonl')

# Stop words for keyword extraction from market titles
_STOP_WORDS = {
    'will', 'the', 'a', 'an', 'be', 'in', 'on', 'by', 'to', 'of', 'for',
    'is', 'are', 'was', 'were', 'this', 'that', 'before', 'after', 'from',
    'with', 'have', 'has', 'been', 'any', 'more', 'than', 'its', 'their',
    'does', 'did', 'do', 'not', 'and', 'or', 'but', 'if', 'at', 'into',
    'during', 'between', 'through', 'about', 'over', 'under', 'above',
    'effect', 'place', 'take', 'happen', 'occur', 'yes', 'no',
}

# Time budget for entire geo scan
_TIME_BUDGET_SECONDS = 300  # 5 minutes


def _extract_search_keywords(title):
    """
    Extract GDELT search keywords from a Kalshi market title.
    Returns a search query string targeting the specific market topic.
    """
    if not title:
        return ''
    # Remove common prediction market framing
    cleaned = re.sub(r'(Will |Will there be |Is |Are |Does |Has |Have )', '', title, flags=re.IGNORECASE)
    cleaned = re.sub(r'\?$', '', cleaned)
    # Remove date references (e.g., "by March 31", "before April 1, 2026")
    cleaned = re.sub(r'\b(by|before|after|on|in)\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(,?\s*\d{4})?\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b\d{4}\b', '', cleaned)

    words = cleaned.split()
    keywords = [w.strip('.,;:!?()[]') for w in words if w.lower().strip('.,;:!?()[]') not in _STOP_WORDS and len(w) > 2]
    # Take the most meaningful words (up to 6)
    return ' '.join(keywords[:6])


def run_geo_scan():
    """
    Market-first geopolitical scan:
    1. Fetch open Kalshi geo markets via KalshiClient
    2. For each market with yes_ask 5-92c, query GDELT for relevant news
    3. Run Stage 1 (Haiku) screen on best GDELT hit
    4. If severity >= 3, run Stage 2 (Sonnet) probability estimate
    5. If edge > GEO_MIN_EDGE_THRESHOLD, add to results
    Returns list of opportunity dicts.
    """
    log_activity("[Geo] Starting market-first geopolitical scan...")
    start_time = time.monotonic()

    # Step 1: Fetch open geo markets with live prices
    try:
        kalshi = KalshiClient()
        markets = search_geo_markets(kalshi, max_markets=50)
    except Exception as e:
        log_activity(f"[Geo] Failed to fetch Kalshi markets: {e}")
        return []

    if not markets:
        log_activity("[Geo] No open geopolitical markets found")
        return []

    # Filter to tradeable price range (5-92 cents)
    tradeable = []
    for m in markets:
        yes_ask = m.get('yes_ask') or 0
        if 5 <= yes_ask <= 92:
            tradeable.append(m)

    log_activity(f"[Geo] {len(markets)} total geo markets, {len(tradeable)} in tradeable range (5-92c)")

    if not tradeable:
        return []

    # Step 2-5: For each market, query GDELT -> Stage 1 -> Stage 2 -> edge calc
    opportunities = []
    gdelt_failures = 0
    max_gdelt_failures = 5  # circuit breaker

    for m in tradeable:
        # Time budget check
        elapsed = time.monotonic() - start_time
        if elapsed > _TIME_BUDGET_SECONDS:
            log_activity(f"[Geo] Time budget exceeded ({elapsed:.0f}s) — stopping scan")
            break

        ticker = m.get('ticker', '')
        title = m.get('title', '') or ''
        yes_ask = m.get('yes_ask', 0)
        days = _days_to_expiry(m)

        # Skip same-day expiry
        if days is not None and days < cfg.GEO_MIN_DAYS_TO_EXPIRY:
            continue

        # Step 2: Extract keywords and query GDELT
        search_query = _extract_search_keywords(title)
        if not search_query:
            continue

        if gdelt_failures >= max_gdelt_failures:
            log_activity("[Geo] GDELT circuit breaker — skipping remaining markets")
            break

        try:
            events = get_gdelt_events(query=search_query, timespan='24h', max_records=10)
            gdelt_failures = 0  # reset on success
        except _GdeltRequestFailed:
            gdelt_failures += 1
            continue
        except Exception:
            gdelt_failures += 1
            continue

        if not events:
            continue

        # Pick the highest-severity event for this market
        events.sort(key=lambda e: e.get('severity', 0), reverse=True)
        best_event = events[0]

        # Step 3: Stage 1 — Haiku screen
        try:
            s1 = stage1_classify(best_event, title)
        except Exception as e:
            log_activity(f"[Geo] Stage 1 error for {ticker}: {e}")
            continue

        if s1 is None or not s1.get('relevant') or s1.get('severity', 0) < 3:
            continue

        # Step 4: Stage 2 — Sonnet probability estimate
        try:
            s2 = stage2_estimate(best_event, title, yes_ask, days)
        except Exception as e:
            log_activity(f"[Geo] Stage 2 error for {ticker}: {e}")
            continue

        if s2 is None:
            continue

        # Step 5: Calculate edge
        market_prob = yes_ask / 100
        estimated_prob = s2['estimated_prob']
        edge = abs(estimated_prob - market_prob)

        if edge < cfg.GEO_MIN_EDGE_THRESHOLD:
            continue

        direction = 'YES' if estimated_prob > market_prob else 'NO'
        confidence = s2['confidence']

        if confidence < cfg.MIN_CONFIDENCE.get('geo', 0.50):
            continue

        opportunity = {
            'ticker': ticker,
            'title': title,
            'yes_ask': yes_ask,
            'market_prob': round(market_prob, 3),
            'estimated_prob': estimated_prob,
            'edge': round(edge, 4),
            'direction': direction,
            'confidence': confidence,
            'reasoning': s2['reasoning'],
            'days_to_expiry': round(days, 2) if days is not None else None,
            'stage1_severity': s1['severity'],
            'stage1_event_type': s1['event_type'],
            'news_headline': best_event.get('title', '')[:120],
            'news_count': len(events),
            'module': 'geo',
        }
        opportunities.append(opportunity)
        log_activity(f"[Geo] EDGE: {ticker} | {direction} @ {yes_ask}c | edge={edge:.1%} conf={confidence:.0%} | {s2['reasoning'][:60]}")

    # Sort by edge descending
    opportunities.sort(key=lambda x: x['edge'], reverse=True)

    # Log all opportunities
    try:
        os.makedirs(os.path.dirname(GEO_LOG), exist_ok=True)
        with open(GEO_LOG, 'a', encoding='utf-8') as f:
            for opp in opportunities:
                f.write(json.dumps({'date': str(date.today()), **opp}) + '\n')
    except Exception:
        pass

    log_activity(f"[Geo] Scan complete: {len(tradeable)} markets screened, {len(opportunities)} opportunities with edge > {cfg.GEO_MIN_EDGE_THRESHOLD:.0%}")
    return opportunities


def format_geo_brief(opportunities, max_show=5):
    """Format geopolitical opportunities brief for review."""
    if not opportunities:
        return "No geopolitical edge opportunities found."

    lines = [f"GEOPOLITICAL EDGE SCAN -- {date.today().strftime('%b %d')}",
             "=" * 50,
             f"{len(opportunities)} opportunities with edge:\n"]

    for i, opp in enumerate(opportunities[:max_show], 1):
        title = (opp.get('title') or '').encode('ascii', 'replace').decode()
        lines.append(f"{i}. {title[:70]}")
        lines.append(f"   {opp['direction']} @ {opp['yes_ask']}c | Edge: {opp['edge']:.1%} | Conf: {opp['confidence']:.0%}")
        lines.append(f"   Est prob: {opp['estimated_prob']:.0%} vs market: {opp['market_prob']:.0%}")
        lines.append(f"   Reason: {opp.get('reasoning', '')[:80]}")
        lines.append(f"   News: {opp.get('news_headline', '')[:70]}")
        lines.append("")

    return '\n'.join(lines)


if __name__ == '__main__':
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    opportunities = run_geo_scan()
    brief = format_geo_brief(opportunities)
    print(brief)
