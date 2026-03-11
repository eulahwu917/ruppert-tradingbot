"""Debug: dump all open Kalshi market titles to see what's available."""
import sys, io, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

resp = requests.get(
    'https://api.elections.kalshi.com/trade-api/v2/markets',
    params={'limit': 200, 'status': 'open'},
    timeout=15
)
markets = resp.json().get('markets', [])
print(f"Total open markets: {len(markets)}")
print()

# Show all unique categories
categories = set()
for m in markets:
    cat = m.get('category') or m.get('series_ticker', '?')[:10]
    categories.add(cat)
print(f"Categories: {sorted(categories)}")
print()

# Show all titles
print("All market titles:")
for m in markets:
    title = (m.get('title') or '').encode('ascii', 'replace').decode()
    print(f"  {title[:90]}")
