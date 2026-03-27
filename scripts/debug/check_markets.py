import requests
from datetime import datetime, timezone

BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"
now = datetime.now(timezone.utc)

# Fetch with pagination to get ALL BTC markets
all_markets = []
cursor = None
while True:
    params = {'series_ticker': 'KXBTC', 'status': 'open', 'limit': 100}
    if cursor:
        params['cursor'] = cursor
    r = requests.get(BASE, params=params, timeout=10)
    data = r.json()
    batch = data.get('markets', [])
    all_markets.extend(batch)
    cursor = data.get('cursor')
    print(f"Fetched {len(batch)} markets (total so far: {len(all_markets)}, cursor: {cursor})")
    if not cursor or not batch:
        break

print(f"\nTotal BTC markets: {len(all_markets)}")

# Show liquid ones (yes_ask_dollars between 0.03 and 0.95)
liquid = []
for m in all_markets:
    ya_d = float(m.get('yes_ask_dollars') or 0)
    na_d = float(m.get('no_ask_dollars') or 0)
    ya = round(ya_d * 100)
    na = round(na_d * 100)
    if 3 <= ya <= 95:
        liquid.append((m.get('ticker',''), ya, na, m.get('floor_strike', 0)))

liquid.sort(key=lambda x: x[3])
print(f"Liquid markets (ya 3-95c): {len(liquid)}")
for t, ya, na, strike in liquid:
    print(f"  {t:50} ya={ya:3}c na={na:3}c  strike=${strike:,.0f}")
