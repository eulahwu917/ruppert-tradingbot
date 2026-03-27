import requests, json

# Unauthenticated fetch — what does the raw API return for yes_ask/no_ask?
BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"
HDR = {"Accept": "application/json"}

r = requests.get(BASE, params={'series_ticker': 'KXBTC', 'status': 'open', 'limit': 5}, headers=HDR, timeout=8)
markets = r.json().get('markets', [])
if markets:
    print("Sample market fields:")
    print(json.dumps(markets[0], indent=2))
else:
    print("No markets:", r.json())
