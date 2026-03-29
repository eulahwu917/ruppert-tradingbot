"""Pull Kalshi settled crypto markets and update manifest."""
import json, time, requests
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(r"C:\Users\David Wu\.openclaw\workspace\ruppert-backtest\data")
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
CRYPTO_SERIES = ["KXBTC", "KXETH", "KXXRP", "KXSOL", "KXDOGE"]

print("=== Kalshi: Pulling settled crypto markets ===")
crypto_markets = []
series_with_data = []
series_empty = []

for series in CRYPTO_SERIES:
    try:
        r = requests.get(f"{KALSHI_BASE}/markets",
                         params={"series_ticker": series, "status": "settled", "limit": 50},
                         timeout=15)
        r.raise_for_status()
        markets = r.json().get("markets", [])
        extracted = [{
            "ticker":        m.get("ticker"),
            "series_ticker": m.get("series_ticker"),
            "close_time":    m.get("close_time"),
            "last_price":    m.get("last_price"),
            "yes_ask":       m.get("yes_ask"),
            "yes_bid":       m.get("yes_bid"),
            "open_time":     m.get("open_time"),
            "subtitle":      m.get("subtitle"),
        } for m in markets]
        crypto_markets.extend(extracted)
        if extracted:
            series_with_data.append(series)
            print(f"  {series}: {len(extracted)} settled markets")
        else:
            series_empty.append(series)
            print(f"  {series}: 0 results (EMPTY)")
    except Exception as e:
        print(f"  {series}: ERROR - {e}")
        series_empty.append(series)
    time.sleep(0.1)

# Save
out_path = DATA_DIR / "kalshi_settled_crypto.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(crypto_markets, f, indent=2)
print(f"\nSaved {len(crypto_markets)} crypto markets to {out_path}")

# Update manifest
manifest_path = DATA_DIR / "manifest.json"
manifest = json.load(open(manifest_path, encoding="utf-8"))
manifest["kalshi_crypto_markets"] = len(crypto_markets)
manifest["pulled_at"] = datetime.now(timezone.utc).isoformat()
manifest["validation"]["kalshi_crypto_series_with_data"] = series_with_data
manifest["validation"]["kalshi_crypto_series_empty"] = series_empty
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print(f"Manifest updated. Crypto: {len(crypto_markets)} markets, {len(series_with_data)}/{len(CRYPTO_SERIES)} series with data.")
print(f"Empty series: {series_empty or 'none'}")
