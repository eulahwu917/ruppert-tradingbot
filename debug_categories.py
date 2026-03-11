"""Find correct Kalshi series tickers for economics, politics, gaming."""
import sys, io, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Try fetching events (broader than markets)
print("=== EVENTS (sampling) ===")
resp = requests.get(
    'https://api.elections.kalshi.com/trade-api/v2/events',
    params={'limit': 50, 'status': 'open'},
    timeout=15
)
events = resp.json().get('events', [])
print(f"Total events: {len(events)}")
for e in events[:20]:
    title = (e.get('title') or '').encode('ascii', 'replace').decode()
    series = e.get('series_ticker', '?')
    category = e.get('category', '?')
    print(f"  [{series}] [{category}] {title[:80]}")

print()
# Try series endpoint
print("=== SERIES (sampling) ===")
resp2 = requests.get(
    'https://api.elections.kalshi.com/trade-api/v2/series',
    params={'limit': 50},
    timeout=15
)
data2 = resp2.json()
series_list = data2.get('series', [])
print(f"Total series: {len(series_list)}")
for s in series_list[:30]:
    title = (s.get('title') or '').encode('ascii', 'replace').decode()
    ticker = s.get('ticker', '?')
    category = s.get('category', '?')
    freq = s.get('frequency', '?')
    print(f"  [{ticker}] [{category}] {title[:70]}")
