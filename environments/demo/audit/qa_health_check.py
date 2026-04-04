"""
QA API Health Check - SA-4
Run: python qa_health_check.py
"""
import sys
import json
import time
import traceback
from datetime import date, timedelta
sys.path.insert(0, '.')

results = {}

# ─── API 1: Kalshi Market Data (public) ───────────────────────────────────────
print("\n=== API 1: Kalshi Market Data (Public) ===")
try:
    import requests
    BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"
    r = requests.get(BASE, params={'series_ticker': 'KXHIGHMIA', 'status': 'open', 'limit': 5}, timeout=8)
    if r.status_code == 200:
        data = r.json()
        markets = data.get('markets', [])
        ticker = markets[0].get('ticker', '') if markets else ''
        print(f"  Status: {r.status_code}, Markets: {len(markets)}, Sample ticker: {ticker}")
        
        # Test orderbook
        if ticker:
            r2 = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook", timeout=5)
            ob = r2.json().get('orderbook_fp', {})
            no_d = ob.get('no_dollars', [])
            yes_d = ob.get('yes_dollars', [])
            print(f"  Orderbook for {ticker}: status={r2.status_code}, no_dollars_rows={len(no_d)}, yes_dollars_rows={len(yes_d)}")
            results['api1'] = {
                'status': 'PASS',
                'markets': len(markets),
                'ticker': ticker,
                'orderbook_status': r2.status_code,
                'no_dollars_rows': len(no_d),
                'yes_dollars_rows': len(yes_d)
            }
        else:
            results['api1'] = {'status': 'PARTIAL', 'note': 'No open markets for KXHIGHMIA', 'markets': 0}
    else:
        print(f"  FAIL: {r.status_code} {r.text[:200]}")
        results['api1'] = {'status': 'FAIL', 'http_code': r.status_code}
except Exception as e:
    print(f"  EXCEPTION: {e}")
    results['api1'] = {'status': 'FAIL', 'error': str(e)}

# ─── API 2: Kalshi Authenticated (Balance) ────────────────────────────────────
print("\n=== API 2: Kalshi Authenticated (Balance) ===")
try:
    from kalshi_client import KalshiClient
    client = KalshiClient()
    bal = client.get_balance()
    print(f"  Balance: ${bal:.2f}")
    results['api2'] = {'status': 'PASS', 'balance': bal}
except Exception as e:
    print(f"  EXCEPTION: {e}")
    results['api2'] = {'status': 'FAIL', 'error': str(e)}

# ─── API 4: Kraken — 5 crypto pairs ──────────────────────────────────────────
print("\n=== API 4: Kraken — 5 crypto pairs ===")
kraken_pairs = [
    ('XBTUSD', 'btc'),
    ('ETHUSD', 'eth'),
    ('XRPUSD', 'xrp'),
    ('SOLUSD', 'sol'),
    ('XDGEUSD', 'doge'),
]
kraken_results = {}
for sym, key in kraken_pairs:
    try:
        r = requests.get(f'https://api.kraken.com/0/public/Ticker?pair={sym}', timeout=5)
        data = r.json()
        if r.status_code == 200 and not data.get('error'):
            result_keys = list(data.get('result', {}).keys())
            if result_keys:
                price = data['result'][result_keys[0]]['c'][0]
                print(f"  ✅ {sym}/{key}: ${float(price):,.2f}")
                kraken_results[sym] = {'status': 'PASS', 'price': price}
            else:
                print(f"  ❌ {sym}: empty result")
                kraken_results[sym] = {'status': 'FAIL', 'note': 'empty result'}
        elif data.get('error'):
            # Try alternate symbol for DOGE
            if sym == 'XDGEUSD':
                r2 = requests.get(f'https://api.kraken.com/0/public/Ticker?pair=DOGEUSD', timeout=5)
                data2 = r2.json()
                if r2.status_code == 200 and not data2.get('error'):
                    result_keys2 = list(data2.get('result', {}).keys())
                    if result_keys2:
                        price2 = data2['result'][result_keys2[0]]['c'][0]
                        print(f"  ✅ DOGEUSD (fallback): ${float(price2):,.4f}")
                        kraken_results[sym] = {'status': 'PASS', 'note': 'used DOGEUSD fallback', 'price': price2}
                    else:
                        print(f"  ❌ DOGEUSD fallback also failed")
                        kraken_results[sym] = {'status': 'FAIL', 'error': str(data2.get('error'))}
                else:
                    print(f"  ❌ DOGEUSD fallback: {data2.get('error')}")
                    kraken_results[sym] = {'status': 'FAIL', 'error': str(data2.get('error'))}
            else:
                print(f"  ❌ {sym}: Kraken error {data.get('error')}")
                kraken_results[sym] = {'status': 'FAIL', 'error': str(data.get('error'))}
        else:
            print(f"  ❌ {sym}: HTTP {r.status_code}")
            kraken_results[sym] = {'status': 'FAIL', 'http_code': r.status_code}
    except Exception as e:
        print(f"  ❌ {sym}: EXCEPTION {e}")
        kraken_results[sym] = {'status': 'FAIL', 'error': str(e)}

results['api4_kraken'] = kraken_results

# ─── API 5: Polymarket — FOMC slug ────────────────────────────────────────────
print("\n=== API 5: Polymarket — FOMC slug ===")
try:
    r = requests.get('https://gamma-api.polymarket.com/events?slug=fed-decision-in-march-885', timeout=10)
    if r.status_code == 200:
        data = r.json()
        events = data if isinstance(data, list) else data.get('events', [data])
        if events:
            event = events[0]
            markets_pm = event.get('markets', [])
            title = event.get('title', event.get('slug', 'unknown'))
            print(f"  Title: {title}")
            print(f"  Markets: {len(markets_pm)}")
            if markets_pm:
                m0 = markets_pm[0]
                outcome_prices = m0.get('outcomePrices', m0.get('prices', ''))
                print(f"  Sample market: {m0.get('question', m0.get('groupItemTitle', '')[:80])}")
                print(f"  Prices: {outcome_prices}")
            results['api5'] = {
                'status': 'PASS',
                'title': title,
                'market_count': len(markets_pm),
                'sample_prices': str(outcome_prices)[:100] if markets_pm else None
            }
        else:
            print(f"  PARTIAL: 200 but empty events")
            results['api5'] = {'status': 'PARTIAL', 'note': 'empty events', 'raw': str(data)[:200]}
    else:
        print(f"  FAIL: {r.status_code} {r.text[:200]}")
        results['api5'] = {'status': 'FAIL', 'http_code': r.status_code}
except Exception as e:
    print(f"  EXCEPTION: {e}")
    results['api5'] = {'status': 'FAIL', 'error': str(e)}

# ─── API 8: Kalshi search_markets() with orderbook enrichment ─────────────────
print("\n=== API 8: Kalshi search_markets() with orderbook enrichment ===")
try:
    if 'client' not in dir():
        from kalshi_client import KalshiClient
        client = KalshiClient()
    markets = client.search_markets('temperature')
    priced = [m for m in markets if m.get('yes_bid') or m.get('yes_ask')]
    print(f"  Total: {len(markets)}, Priced: {len(priced)}")
    pct = (len(priced)/len(markets)*100) if markets else 0
    print(f"  Price coverage: {pct:.1f}%")
    if priced:
        sample = priced[0]
        print(f"  Sample: {sample.get('ticker')} yes_bid={sample.get('yes_bid')} yes_ask={sample.get('yes_ask')}")
    
    status = 'PASS' if pct > 30 else ('PARTIAL' if markets else 'FAIL')
    results['api8'] = {
        'status': status,
        'total_markets': len(markets),
        'priced_markets': len(priced),
        'price_coverage_pct': round(pct, 1)
    }
except Exception as e:
    print(f"  EXCEPTION: {e}")
    traceback.print_exc()
    results['api8'] = {'status': 'FAIL', 'error': str(e)}

# ─── Save raw results ─────────────────────────────────────────────────────────
import os
os.makedirs('memory/agents', exist_ok=True)
with open('memory/agents/qa_raw_results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\n=== Done. Results saved to memory/agents/qa_raw_results.json ===")
print(json.dumps(results, indent=2))
