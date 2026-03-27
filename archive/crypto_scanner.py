"""
Crypto Market Scanner
Scans all active KXBTC, KXETH, KXXRP, KXDOGE markets on Kalshi.
Flags opportunities where model probability diverges from market price by >10%.

ALL flagged trades are SEMI-AUTO — David must approve before execution.

Author: Ruppert (AI Trading Analyst)
Updated: 2026-03-10
"""

import requests
import sys
import time
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from crypto_client import (
    get_btc_signal,
    get_eth_signal,
    get_xrp_signal,
    get_doge_signal,
    get_polymarket_smart_money,
    get_crypto_edge,
)
import config

BASE = 'https://api.elections.kalshi.com/trade-api/v2'
HEADERS = {'User-Agent': 'KalshiCryptoBot/1.0'}

# Active crypto series on Kalshi (verified 2026-03-10)
CRYPTO_SERIES = ['KXBTC', 'KXETH', 'KXXRP', 'KXDOGE']

# Minimum edge to flag (10%)
MIN_EDGE = 0.10

# Minimum absolute edge to flag NO side (NO edge is inverted)
MIN_NO_EDGE = 0.10

# Minimum volume (0 ok for brand-new markets, but prefer some liquidity)
MIN_VOLUME = 0  # crypto markets are thin; don't filter by volume

# Confidence filter
CONFIDENCE_FILTER = ['medium', 'high']

# Max markets to fetch per series (pagination)
FETCH_LIMIT = 100


def fetch_all_markets(series_ticker: str) -> list:
    """
    Fetch ALL open markets for a series using pagination.
    Groups by event_ticker so we can compute band structure.
    """
    all_markets = []
    cursor = None

    while True:
        params = {'series_ticker': series_ticker, 'status': 'open', 'limit': 100}
        if cursor:
            params['cursor'] = cursor

        try:
            r = requests.get(f'{BASE}/markets', params=params, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f'[CryptoScanner] HTTP {r.status_code} for {series_ticker}')
                break
            data = r.json()
            markets = data.get('markets', [])
            all_markets.extend(markets)
            cursor = data.get('cursor')
            if not cursor or not markets:
                break
        except Exception as e:
            print(f'[CryptoScanner] Error fetching {series_ticker}: {e}')
            break

    return all_markets


def group_by_event(markets: list) -> dict:
    """Group markets by event_ticker. Returns {event_ticker: [markets]}."""
    groups = defaultdict(list)
    for m in markets:
        event = m.get('event_ticker', '')
        groups[event].append(m)
    return dict(groups)


def scan_series(series: str, price_signals: dict, smart_money: dict) -> list:
    """
    Scan one crypto series and return list of opportunity dicts.
    """
    print(f'\n[{series}] Fetching open markets...', flush=True)
    markets = fetch_all_markets(series)
    print(f'[{series}] Found {len(markets)} open markets across all events')

    if not markets:
        return []

    # Group by event
    events = group_by_event(markets)
    print(f'[{series}] {len(events)} events: {list(events.keys())}')

    opportunities = []

    for event_ticker, event_markets in events.items():
        # Find the next-settling event (earliest close_time)
        close_times = [m.get('close_time', '') for m in event_markets if m.get('close_time')]
        if not close_times:
            continue
        event_close = min(close_times)

        # Skip expired events
        try:
            close_dt = datetime.fromisoformat(event_close.replace('Z', '+00:00'))
            if close_dt < datetime.now(timezone.utc):
                continue
        except Exception:
            pass

        print(f'  Event {event_ticker}: {len(event_markets)} markets, closes {event_close[:16]}Z')

        for market in event_markets:
            edge_result = get_crypto_edge(market, all_event_markets=event_markets)
            if not edge_result:
                continue

            edge = edge_result['edge']
            confidence = edge_result['confidence']
            abs_edge = abs(edge)

            # Filter: edge threshold + confidence
            if abs_edge < MIN_EDGE:
                continue
            if confidence not in CONFIDENCE_FILTER:
                continue

            opportunities.append(edge_result)
            direction_label = 'BUY YES' if edge > 0 else 'BUY NO'
            print(f'    *** OPPORTUNITY: {market["ticker"][-20:]} | '
                  f'edge={edge:+.1%} | {direction_label} | conf={confidence}')

    return opportunities


def format_opportunity(opp: dict, rank: int) -> str:
    """Format one opportunity for display."""
    ticker = opp['ticker']
    asset = opp.get('asset', '?')
    edge = opp['edge']
    market_prob = opp['market_prob']
    model_prob = opp['model_prob']
    confidence = opp['confidence']
    direction = opp['direction']
    price = opp.get('current_price', 0)
    strike = opp.get('strike', 0)
    hours = opp.get('hours_to_settlement', 0)
    volume = opp.get('volume', 0)
    momentum = opp.get('momentum', 'NEUTRAL')
    sm = opp.get('smart_money', {})
    sm_dir = sm.get('direction', 'NEUTRAL')

    yes_ask = opp.get('yes_ask', 0)
    yes_bid = opp.get('yes_bid', 0)
    oi = opp.get('open_interest', 0)
    floor_s = opp.get('floor_strike', strike)
    cap_s = opp.get('cap_strike', '')

    side_label = 'BUY YES' if edge > 0 else 'BUY NO'
    band_str = f'[{floor_s:g}, {cap_s:g}]' if (cap_s is not None and cap_s != '') else (f'{floor_s:g}+' if floor_s is not None else '?')

    lines = [
        f'#{rank} [{asset}] {ticker}',
        f'  Band: {band_str} | Current: {price:g}',
        f'  Market: {market_prob:.0%} YES (ask={yes_ask}c, bid={yes_bid}c) | Model: {model_prob:.1%} | Edge: {edge:+.1%}',
        f'  Action: {side_label}',
        f'  Expires in: {hours:.1f}h | Vol: {volume} | OI: {oi} | Conf: {confidence.upper()}',
        f'  Momentum: {momentum} | Smart money: {sm_dir}',
        f'  Reasoning: {opp["reasoning"][:130]}',
        f'  [!] REQUIRES DAVID APPROVAL',
    ]
    return '\n'.join(lines)


def run_scan(verbose: bool = True) -> list:
    """
    Main scan function. Returns list of opportunity dicts.
    Prints results to stdout.
    """
    now = datetime.now(timezone.utc)
    print(f'\n{"="*60}')
    print(f'CRYPTO SCANNER — {now.strftime("%Y-%m-%d %H:%M UTC")}')
    print(f'{"="*60}')

    # ── Pre-fetch all signals (avoids repeated API calls)
    print('\n[Signals] Fetching live price signals...')
    price_signals = {}
    signal_fns = {'BTC': get_btc_signal, 'ETH': get_eth_signal,
                  'XRP': get_xrp_signal, 'DOGE': get_doge_signal}
    for sym, fn in signal_fns.items():
        try:
            sig = fn()
            price_signals[sym] = sig
            rsi_str = f'{sig["rsi"]:.1f}' if sig.get('rsi') else 'N/A'
            print(f'  {sym}: ${sig["price"]:,.4f} | {sig["direction"]} | '
                  f'RSI={rsi_str} | 24h={sig.get("change_24h", 0):+.2f}%')
        except Exception as e:
            print(f'  {sym}: ERROR — {e}')
        time.sleep(0.8)  # respect CoinGecko rate limit

    # ── Smart money
    print('\n[Smart Money] Fetching Polymarket positions...')
    smart_money = get_polymarket_smart_money()
    print(f'  Available: {smart_money["available"]} | '
          f'Reason: {smart_money["reason"]} | '
          f'Wallets tracked: {smart_money["tracked_wallets"]}')
    for asset in ['BTC', 'ETH']:
        sm = smart_money.get(asset, {})
        print(f'  {asset}: {sm.get("direction", "NEUTRAL")} '
              f'({sm.get("bull", 0)} bull / {sm.get("bear", 0)} bear)')

    # ── Scan each series
    all_opportunities = []
    for series in CRYPTO_SERIES:
        opps = scan_series(series, price_signals, smart_money)
        all_opportunities.extend(opps)
        time.sleep(0.5)

    # ── Sort by |edge| descending
    all_opportunities.sort(key=lambda x: abs(x['edge']), reverse=True)

    # ── Print results
    print(f'\n{"="*60}')
    print(f'RESULTS: {len(all_opportunities)} opportunities found')
    print(f'{"="*60}')

    if not all_opportunities:
        print('\nNo opportunities meeting threshold (|edge| > 10%, conf=medium+).')
        print('Market may be fairly priced or bands too far from current price.')
    else:
        for i, opp in enumerate(all_opportunities[:10], 1):
            print()
            print(format_opportunity(opp, i))

    # ── Summary table
    print(f'\n{"─"*60}')
    print('SUMMARY TABLE')
    print(f'{"─"*60}')
    print(f'{"Ticker":<35} {"Edge":>7} {"Action":<10} {"Conf":<8} {"EV/100":>8}')
    print(f'{"─"*60}')
    for opp in all_opportunities[:15]:
        ticker_short = opp['ticker'].split('-')[-1]
        ev = abs(opp['edge']) * (100 if opp['edge'] > 0 else 100)
        action = f'BUY {opp["direction"]}'
        print(f'{opp["ticker"]:<35} {opp["edge"]:>+7.1%} {action:<10} '
              f'{opp["confidence"]:<8} ${ev*abs(opp["edge"]):.2f}')

    return all_opportunities


if __name__ == '__main__':
    opportunities = run_scan(verbose=True)

    # Save opportunities to log
    log_path = 'logs/crypto_scan_latest.json'
    try:
        import os
        os.makedirs('logs', exist_ok=True)
        with open(log_path, 'w') as f:
            # Exclude non-serializable signal sub-dicts
            clean = []
            for opp in opportunities:
                o = dict(opp)
                o.pop('signal', None)
                clean.append(o)
            json.dump({
                'scan_time': datetime.now(timezone.utc).isoformat(),
                'opportunities': clean,
            }, f, indent=2, default=str)
        print(f'\n[Saved] {log_path}')
    except Exception as e:
        print(f'[Save failed] {e}')
