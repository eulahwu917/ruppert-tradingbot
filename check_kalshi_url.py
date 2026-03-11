import sys, json, requests
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from kalshi_client import KalshiClient

client = KalshiClient()
# Direct API call to get one market
resp = client.session.get(
    f"{client.base_url}/markets",
    params={"series_ticker": "KXHIGHMIA", "limit": 1}
)
data = resp.json()
markets = data.get('markets', [])
if markets:
    m = markets[0]
    print("ticker:", m.get('ticker'))
    print("title:", m.get('title'))
    print("market_url:", m.get('market_url'))
    print("yes_sub_title:", m.get('yes_sub_title'))
    # Print any url-looking fields
    for k, v in m.items():
        if 'url' in k.lower() or 'link' in k.lower() or 'slug' in k.lower():
            print(f"  URL field -> {k}: {v}")
