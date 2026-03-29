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

if __name__ != '__main__':
    raise ImportError("qa_health_check.py is a standalone script — do not import it")

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

# ─── API 3: NOAA/NWS — all 19 cities ─────────────────────────────────────────
print("\n=== API 3: NOAA/NWS — all 19 cities ===")
NWS_GRID_POINTS = {
    "KXHIGHNY":    {"office": "OKX", "gridX": 37,  "gridY": 39,  "city": "New York"},
    "KXHIGHCHI":   {"office": "LOT", "gridX": 66,  "gridY": 77,  "city": "Chicago"},
    "KXHIGHMIA":   {"office": "MFL", "gridX": 106, "gridY": 51,  "city": "Miami"},
    "KXHIGHPHX":   {"office": "PSR", "gridX": 157, "gridY": 57,  "city": "Phoenix"},
    "KXHIGHHOU":   {"office": "HGX", "gridX": 66,  "gridY": 99,  "city": "Houston"},
    # New cities (weather_series in kalshi_client.py)
    "KXHIGHAUS":   {"office": "EWX", "gridX": 156, "gridY": 91,  "city": "Austin"},
    "KXHIGHDEN":   {"office": "BOU", "gridX": 63,  "gridY": 62,  "city": "Denver"},
    "KXHIGHLAX":   {"office": "LOX", "gridX": 148, "gridY": 41,  "city": "Los Angeles (LAX)"},
    "KXHIGHPHIL":  {"office": "PHI", "gridX": 50,  "gridY": 76,  "city": "Philadelphia"},
    "KXHIGHTMIN":  {"office": "MPX", "gridX": 108, "gridY": 72,  "city": "Minneapolis"},
    "KXHIGHTDAL":  {"office": "FWD", "gridX": 87,  "gridY": 107, "city": "Dallas"},
    "KXHIGHTDC":   {"office": "LWX", "gridX": 96,  "gridY": 72,  "city": "Washington DC"},
    "KXHIGHTLV":   {"office": "VEF", "gridX": 123, "gridY": 98,  "city": "Las Vegas"},
    "KXHIGHTNOU":  {"office": "LIX", "gridX": 68,  "gridY": 88,  "city": "New Orleans"},
    "KXHIGHTOKC":  {"office": "OUN", "gridX": 97,  "gridY": 94,  "city": "Oklahoma City"},
    "KXHIGHTSFO":  {"office": "MTR", "gridX": 85,  "gridY": 98,  "city": "San Francisco"},
    "KXHIGHTSEA":  {"office": "SEW", "gridX": 124, "gridY": 61,  "city": "Seattle"},
    "KXHIGHTSATX": {"office": "EWX", "gridX": 126, "gridY": 54,  "city": "San Antonio"},
    "KXHIGHTATL":  {"office": "FFC", "gridX": 50,  "gridY": 82,  "city": "Atlanta"},
}

nws_results = {}
for series, cfg_grid in NWS_GRID_POINTS.items():
    try:
        url = f"https://api.weather.gov/gridpoints/{cfg_grid['office']}/{cfg_grid['gridX']},{cfg_grid['gridY']}/forecast"
        r = requests.get(url, timeout=10, headers={'User-Agent': 'RuppertBot/1.0 (qa-check)'})
        if r.status_code == 200:
            periods = r.json().get('properties', {}).get('periods', [])
            temp = periods[0].get('temperature') if periods else None
            unit = periods[0].get('temperatureUnit') if periods else None
            print(f"  ✅ {series} ({cfg_grid['city']}): {r.status_code}, periods={len(periods)}, temp={temp}°{unit}")
            nws_results[series] = {'status': 'PASS', 'periods': len(periods), 'sample_temp': f"{temp}°{unit}"}
        else:
            print(f"  ❌ {series} ({cfg_grid['city']}): {r.status_code} - {r.text[:100]}")
            nws_results[series] = {'status': 'FAIL', 'http_code': r.status_code}
        time.sleep(0.3)  # be polite to NWS
    except Exception as e:
        print(f"  ❌ {series} ({cfg_grid['city']}): EXCEPTION {e}")
        nws_results[series] = {'status': 'FAIL', 'error': str(e)}

results['api3_nws'] = nws_results

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

# ─── API 6: FRED — DFEDTARU ───────────────────────────────────────────────────
print("\n=== API 6: FRED — DFEDTARU ===")
try:
    r = requests.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU', timeout=10)
    if r.status_code == 200:
        lines = r.text.strip().split('\n')
        header = lines[0]
        last_row = lines[-1]
        print(f"  Header: {header}")
        print(f"  Last row: {last_row}")
        parts = last_row.split(',')
        date_val = parts[0] if parts else ''
        rate_val = parts[1] if len(parts) > 1 else ''
        results['api6'] = {
            'status': 'PASS',
            'header': header,
            'latest_date': date_val,
            'latest_rate': rate_val,
            'rows': len(lines) - 1
        }
    else:
        print(f"  FAIL: {r.status_code}")
        results['api6'] = {'status': 'FAIL', 'http_code': r.status_code}
except Exception as e:
    print(f"  EXCEPTION: {e}")
    results['api6'] = {'status': 'FAIL', 'error': str(e)}

# ─── API 7: Open-Meteo via openmeteo_client ───────────────────────────────────
print("\n=== API 7: Open-Meteo (openmeteo_client) ===")
openmeteo_results = {}
try:
    from openmeteo_client import get_full_weather_signal
    # Test Miami (existing city)
    try:
        sig = get_full_weather_signal('KXHIGHMIA', 84.5, (date.today() + timedelta(days=1)).isoformat())
        print(f"  KXHIGHMIA: {sig}")
        if sig and ('prob' in sig or 'probability' in sig or 'confidence' in sig):
            openmeteo_results['KXHIGHMIA'] = {'status': 'PASS', 'signal': str(sig)[:200]}
        else:
            openmeteo_results['KXHIGHMIA'] = {'status': 'PARTIAL', 'signal': str(sig)[:200]}
    except Exception as e:
        print(f"  KXHIGHMIA EXCEPTION: {e}")
        openmeteo_results['KXHIGHMIA'] = {'status': 'FAIL', 'error': str(e)}
    
    # Test Austin (new city)
    try:
        sig2 = get_full_weather_signal('KXHIGHAUS', 82.0, (date.today() + timedelta(days=1)).isoformat())
        print(f"  KXHIGHAUS: {sig2}")
        if sig2 and ('prob' in sig2 or 'probability' in sig2 or 'confidence' in sig2):
            openmeteo_results['KXHIGHAUS'] = {'status': 'PASS', 'signal': str(sig2)[:200]}
        else:
            openmeteo_results['KXHIGHAUS'] = {'status': 'PARTIAL', 'signal': str(sig2)[:200]}
    except Exception as e:
        print(f"  KXHIGHAUS EXCEPTION: {e}")
        openmeteo_results['KXHIGHAUS'] = {'status': 'FAIL', 'error': str(e)}
        
    results['api7_openmeteo'] = openmeteo_results
except Exception as e:
    print(f"  Import EXCEPTION: {e}")
    traceback.print_exc()
    results['api7_openmeteo'] = {'status': 'FAIL', 'error': str(e)}

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
