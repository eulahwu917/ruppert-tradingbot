"""
SA-3 Researcher: Re-pull Kalshi settled market data with per-market fetches.
Fetches last_price, yes_ask, yes_bid, no_ask, no_bid, status, close_time for each ticker.
"""

import json
import time
import urllib.request
import urllib.error
import random
import os

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
HEADERS = {"accept": "application/json"}
SLEEP_BETWEEN = 0.1  # seconds


def fetch_market(ticker, retries=3):
    url = BASE_URL.format(ticker=ticker)
    req = urllib.request.Request(url, headers=HEADERS)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            m = data.get("market", {})
            # Convert dollar string values to float, handle None
            def to_float(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            return {
                "last_price":  to_float(m.get("last_price_dollars")),
                "yes_ask":     to_float(m.get("yes_ask_dollars")),
                "yes_bid":     to_float(m.get("yes_bid_dollars")),
                "no_ask":      to_float(m.get("no_ask_dollars")),
                "no_bid":      to_float(m.get("no_bid_dollars")),
                "status":      m.get("status"),
                "close_time":  m.get("close_time"),
            }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  404 for {ticker} — skipping")
                return None
            elif e.code == 429:
                wait = 2 ** attempt + 1
                print(f"  429 rate limit for {ticker} — waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"  HTTP {e.code} for {ticker} (attempt {attempt+1})")
                time.sleep(1)
        except Exception as e:
            print(f"  Error for {ticker}: {e} (attempt {attempt+1})")
            time.sleep(1)
    return None


def process_file(path):
    print(f"\n=== Processing {path} ===")
    with open(path, encoding="utf-8") as f:
        markets = json.load(f)

    total = len(markets)
    print(f"Total markets: {total}")

    for i, record in enumerate(markets):
        ticker = record["ticker"]
        result = fetch_market(ticker)
        if result:
            record.update(result)
        else:
            # Keep existing nulls if fetch failed
            pass

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{total}")

        time.sleep(SLEEP_BETWEEN)

    # Save back
    with open(path, "w", encoding="utf-8") as f:
        json.dump(markets, f, indent=2, ensure_ascii=False)
    print(f"Saved {total} records to {path}")

    return markets


def validate(markets, label):
    print(f"\n--- Validation: {label} ---")
    total = len(markets)
    populated = sum(1 for m in markets if m.get("last_price") is not None)
    settled = sum(1 for m in markets if m.get("status") in ("finalized", "settled"))

    print(f"Total markets: {total}")
    print(f"last_price NOT null: {populated}/{total}")
    print(f"status == settled/finalized: {settled}/{total}")

    # Spot-check 5 random finalized markets
    finalized = [m for m in markets if m.get("status") in ("finalized", "settled")]
    sample = random.sample(finalized, min(5, len(finalized)))
    print(f"\nSpot-check (5 random settled):")
    for m in sample:
        print(f"  {m['ticker']} | last_price={m.get('last_price')} | status={m.get('status')}")

    return populated, total


def main():
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    weather_path = os.path.join(workspace, "data", "kalshi_settled_weather.json")
    crypto_path  = os.path.join(workspace, "data", "kalshi_settled_crypto.json")

    total_populated = 0
    total_markets = 0

    # Weather
    weather_markets = process_file(weather_path)
    pop, tot = validate(weather_markets, "Weather")
    total_populated += pop
    total_markets += tot

    # Crypto (if exists)
    if os.path.exists(crypto_path):
        crypto_markets = process_file(crypto_path)
        pop2, tot2 = validate(crypto_markets, "Crypto")
        total_populated += pop2
        total_markets += tot2
    else:
        print(f"\nCrypto file not found at {crypto_path} — skipping")

    # Write result marker
    memory_dir = os.path.join(workspace, "..", "memory", "agents")
    os.makedirs(memory_dir, exist_ok=True)
    result_path = os.path.join(memory_dir, "researcher_repull_done.txt")
    msg = f"DONE: last_price populated for {total_populated}/{total_markets} markets"
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(f"\n{msg}")
    print(f"Written to {result_path}")


if __name__ == "__main__":
    main()
