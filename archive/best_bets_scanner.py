"""
Best Bets Scanner
Finds non-weather markets where Ruppert has 60%+ confidence and 15%+ edge vs market.
These always require David's approval before execution.
"""
import requests
import json
from datetime import datetime, date
from pathlib import Path

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Series to scan for best bets (non-weather)
ECONOMICS_SERIES = [
    'KXFED', 'KXCPI', 'KXCPIY', 'KXCPIM', 'KXPCE', 'KXPCEM',
    'KXUE', 'KXLCPIMIN', 'FEDRATEMIN', 'RATEHIKE', 'KXGDP',
    'KXINFL', 'KXINFLATION', 'KXFEDRATE', 'INF', 'CPIM', 'FEDRATE',
    'U3', 'NGDPQ',
]

GEO_SERIES = [
    'KXUKR', 'KXRUSSIA', 'KXCHINA', 'KXIRAN', 'KXNATO',
    'KXMIDEAST', 'KXNKOREA', 'KXTAIWAN', 'KXCONFLICT',
    'KXWW3', 'KXNUCLEAR', 'KXTERROR', 'KXSANCTION',
]

WEATHER_SERIES = ['KXHIGHNY', 'KXHIGHLA', 'KXHIGHCHI', 'KXHIGHHOU', 'KXHIGHMIA', 'KXHIGHPHX']


def fetch_markets_for_series(series_list, limit=20):
    """Fetch open markets for a list of series tickers."""
    markets = []
    for series in series_list:
        try:
            resp = requests.get(
                'https://api.elections.kalshi.com/trade-api/v2/markets',
                params={'series_ticker': series, 'status': 'open', 'limit': limit},
                timeout=5
            )
            if resp.status_code == 200:
                batch = resp.json().get('markets', [])
                markets.extend(batch)
        except Exception:
            pass
    return markets


def fetch_all_open_markets(limit=200):
    """Fetch a broad sample of open markets."""
    try:
        resp = requests.get(
            'https://api.elections.kalshi.com/trade-api/v2/markets',
            params={'status': 'open', 'limit': limit},
            timeout=8
        )
        if resp.status_code == 200:
            return resp.json().get('markets', [])
    except Exception:
        pass
    return []


def market_prob(market):
    """Get implied probability from YES ask price (0.0-1.0)."""
    yes_ask = market.get('yes_ask')
    if yes_ask is not None:
        return yes_ask / 100.0
    return None


def score_economics_market(market):
    """
    Score an economics market.
    Returns (ruppert_prob, confidence, rationale) or None if no edge.
    """
    title = (market.get('title') or '').lower()
    mkt_p = market_prob(market)
    if mkt_p is None:
        return None

    # Fed rate: markets pricing in cuts — consensus is strong
    if any(t in title for t in ['fed rate', 'federal funds', 'fomc', 'rate cut', 'rate hike', 'basis points']):
        # Fed has signaled 2 cuts in 2025 — markets often overprice cuts
        # Heuristic: if market says >70% for a cut, fade slightly
        if mkt_p > 0.80:
            return (0.60, 72, "Fed guidance is cautious — markets overpricing cuts at >80%. Historical: Fed undershoots vs futures pricing.")
        elif mkt_p < 0.20:
            return (0.40, 65, "Low-priced cut market. If Fed stays hawkish, this resolves YES. Monitor CPI.")

    # CPI / Inflation: compare market direction to recent BLS trend
    if any(t in title for t in ['cpi', 'inflation', 'consumer price', 'pce']):
        # March 2026: inflation trending toward 2.5% — markets uncertain
        if 0.35 < mkt_p < 0.65:
            return (0.62, 60, "CPI market near 50/50. Recent BLS trend suggests slight upside. Watch Mar 12 release.")

    # Unemployment
    if any(t in title for t in ['unemployment', 'jobless', 'payroll', 'nonfarm']):
        if mkt_p > 0.75:
            return (0.55, 62, "Labor market resilient — markets may be overpricing weakness.")

    return None


def score_geo_market(market, news_signal='LOW', news_volume=0):
    """
    Score a geopolitical market using fade-the-chaos heuristic.
    Most crises don't escalate. Markets emotionally overprice escalation.
    Returns (ruppert_prob, confidence, rationale) or None if no edge.
    """
    title = (market.get('title') or '').lower()
    mkt_p = market_prob(market)
    if mkt_p is None:
        return None

    # Fade-the-chaos: if market prices escalation high AND news is spiking,
    # the true probability is often lower (emotional pricing)
    escalation_words = ['war', 'attack', 'invade', 'nuclear', 'missile', 'conflict', 'strike', 'coup']
    is_escalation = any(w in title for w in escalation_words)

    if is_escalation and news_signal in ('HIGH', 'MEDIUM') and mkt_p > 0.55:
        conf = 68 if news_signal == 'HIGH' else 62
        ruppert_p = mkt_p * 0.75  # fade by ~25%
        return (round(ruppert_p, 2), conf,
                f"Fade-the-chaos: escalation market at {int(mkt_p*100)}% with {news_signal} news activity. "
                f"Historical base rate for escalation is lower than crowd pricing suggests. "
                f"Recommend NO unless settlement criteria are very specific.")

    # Settlement edge: markets that resolve on very specific criteria often mispriced
    if any(w in title for w in ['before', 'by', 'within']) and 0.15 < mkt_p < 0.45:
        return (mkt_p * 0.9, 60,
                f"Low-priced market ({int(mkt_p*100)}%). Read exact settlement rules — "
                f"specific trigger conditions often make these easier to evaluate than they appear.")

    return None


def find_best_bets(min_confidence=60, min_edge=0.15):
    """
    Main function: find all Best Bets (non-weather) with edge and confidence thresholds.
    Returns list of bet opportunities sorted by confidence.
    """
    from logger import log_activity

    log_activity("[BestBets] Starting scan...")
    results = []

    # --- Economics markets ---
    econ_markets = fetch_markets_for_series(ECONOMICS_SERIES, limit=10)
    log_activity(f"[BestBets] Checking {len(econ_markets)} economics markets")

    for m in econ_markets:
        scored = score_economics_market(m)
        if not scored:
            continue
        ruppert_p, confidence, rationale = scored
        mkt_p = market_prob(m)
        if mkt_p is None:
            continue
        edge = abs(ruppert_p - mkt_p)
        if confidence < min_confidence or edge < min_edge:
            continue

        yes_p = m.get('yes_ask', 0)
        no_p  = 100 - yes_p
        recommended_side = 'YES' if ruppert_p > mkt_p else 'NO'
        recommended_price = yes_p if recommended_side == 'YES' else no_p

        results.append({
            'ticker': m.get('ticker', ''),
            'title': (m.get('title') or '').replace('**', ''),
            'category': 'Economics',
            'market_prob': round(mkt_p, 3),
            'ruppert_prob': ruppert_p,
            'confidence': confidence,
            'edge': round(edge, 3),
            'recommended_side': recommended_side,
            'recommended_price': recommended_price,
            'yes_price': yes_p,
            'no_price': no_p,
            'rationale': rationale,
            'close_date': m.get('close_time', ''),
            'rules': m.get('rules_primary', ''),
            'kalshi_url': f"https://kalshi.com/markets/{m.get('ticker', '')}",
            'source': 'economics',
            'needs_approval': True,
            'date': str(date.today()),
        })

    # --- Geo markets (from scout log) ---
    geo_log = LOGS_DIR / "geopolitical_scout.jsonl"
    if geo_log.exists():
        with open(geo_log, encoding='utf-8') as f:
            for line in f:
                try:
                    m = json.loads(line)
                    if m.get('date') != str(date.today()):
                        continue
                    scored = score_geo_market(
                        {'title': m.get('title',''), 'yes_ask': int((m.get('market_prob',0.5)*100))},
                        news_signal=m.get('news_signal','LOW'),
                        news_volume=m.get('news_volume',0)
                    )
                    if not scored:
                        continue
                    ruppert_p, confidence, rationale = scored
                    mkt_p = m.get('market_prob', 0.5)
                    edge = abs(ruppert_p - mkt_p)
                    if confidence < min_confidence or edge < min_edge:
                        continue

                    yes_p = int(mkt_p * 100)
                    no_p  = 100 - yes_p
                    recommended_side = 'YES' if ruppert_p > mkt_p else 'NO'

                    results.append({
                        'ticker': m.get('ticker', ''),
                        'title': (m.get('title') or '').replace('**', ''),
                        'category': 'Geopolitical',
                        'market_prob': round(mkt_p, 3),
                        'ruppert_prob': ruppert_p,
                        'confidence': confidence,
                        'edge': round(edge, 3),
                        'recommended_side': recommended_side,
                        'recommended_price': no_p if recommended_side == 'NO' else yes_p,
                        'yes_price': yes_p,
                        'no_price': no_p,
                        'rationale': rationale,
                        'close_date': m.get('close_date', ''),
                        'rules': m.get('rules', ''),
                        'news_signal': m.get('news_signal', 'LOW'),
                        'recent_headlines': m.get('recent_headlines', []),
                        'kalshi_url': f"https://kalshi.com/markets/{m.get('ticker', '')}",
                        'source': 'geo',
                        'needs_approval': True,
                        'date': str(date.today()),
                    })
                except Exception:
                    pass

    # Sort by confidence desc, then edge desc
    results.sort(key=lambda x: (x['confidence'], x['edge']), reverse=True)
    log_activity(f"[BestBets] Found {len(results)} best bets (confidence>={min_confidence}%, edge>={int(min_edge*100)}%)")

    # Save to log
    out = LOGS_DIR / "best_bets.jsonl"
    with open(out, 'w', encoding='utf-8') as f:
        for r in results:
            f.write(json.dumps(r) + '\n')

    return results


if __name__ == '__main__':
    bets = find_best_bets()
    print(f"\nFound {len(bets)} Best Bets:\n")
    for b in bets:
        print(f"  [{b['category']}] {b['title'][:60]}")
        print(f"    Market: {int(b['market_prob']*100)}% | Ruppert: {int(b['ruppert_prob']*100)}% | Edge: {int(b['edge']*100)}% | Conf: {b['confidence']}%")
        print(f"    Recommend: {b['recommended_side']} @ {b['recommended_price']}c")
        print(f"    {b['rationale'][:100]}")
        print()
