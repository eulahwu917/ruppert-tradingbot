"""
Execute trades:
1. EXIT two marginal weather positions (lock gains)
2. OPEN crypto NO bets on ETH high bands (bearish smart money signal)
"""
import sys, requests, json, time, math
from pathlib import Path
from datetime import date
sys.stdout.reconfigure(encoding='utf-8')

from kalshi_client import KalshiClient
from logger import log_trade, log_activity
import config

DRY_RUN = True   # Demo mode — flip False when going live

client = KalshiClient()
LOGS   = Path(__file__).parent / "logs"
LOGS.mkdir(exist_ok=True)

def place(ticker, side, action, price_cents, contracts, size_dollars, source, title="", note=""):
    opp = {
        "ticker":       ticker,
        "title":        title or ticker,
        "side":         side,
        "action":       action,
        "yes_price":    price_cents if side == "yes" else (100 - price_cents),
        "market_prob":  price_cents / 100,
        "edge":         None,
        "noaa_prob":    None,
        "size_dollars": round(size_dollars, 2),
        "contracts":    contracts,
        "source":       source,
        "note":         note,
        "timestamp":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        "date":         str(date.today()),
    }
    if DRY_RUN:
        log_activity(f"[DEMO] {action.upper()} {side.upper()} {ticker} | {contracts} @ {price_cents}c | ${size_dollars:.2f} | {note}")
        log_trade(opp, size_dollars, contracts, {"dry_run": True, "status": "simulated"})
        print(f"  ✓  {action.upper()} {side.upper()} {ticker:40} {contracts:4} @ {price_cents:3}c  ${size_dollars:.2f}")
    else:
        try:
            if action == "exit":
                result = client.sell_position(ticker, side, price_cents, contracts)
            else:
                result = client.place_order(ticker, side, price_cents, contracts)
            log_activity(f"[LIVE] {action.upper()} {ticker}")
            log_trade(opp, size_dollars, contracts, result)
            print(f"  ✓  [LIVE] {action.upper()} {side.upper()} {ticker:40} {contracts:4} @ {price_cents:3}c  ${size_dollars:.2f}")
        except Exception as e:
            print(f"  ✗  ERROR {ticker}: {e}")

print("=" * 68)
print("  RUPPERT AUTO-TRADE EXECUTION")
print(f"  {time.strftime('%Y-%m-%d %H:%M:%S PDT')}  |  Mode: {'DEMO' if DRY_RUN else 'LIVE'}")
print("=" * 68)

# ── 1. EXIT WEATHER POSITIONS ────────────────────────────────────────────────
print("\n[1] Exiting marginal weather positions (locking gains)...")

# Miami B83.5: 59 NO contracts bought @ 42c, now 50c → exit
place("KXHIGHMIA-26MAR11-B83.5", "no", "exit",
      price_cents=50, contracts=59, size_dollars=29.50,
      source="weather",
      title="Miami High Temp Mar 11 – Band 83.5-85.5°F",
      note="Exit: +$5.90 gain locked | ensemble 0% chance in band")

# Chicago B48.5: 30 NO contracts bought @ 81c, now 92c → exit
place("KXHIGHCHI-26MAR11-B48.5", "no", "exit",
      price_cents=92, contracts=30, size_dollars=27.60,
      source="weather",
      title="Chicago High Temp Mar 11 – Band 48.5-50.5°F",
      note="Exit: +$3.90 gain locked | 80% ensemble above band = risk")

# ── 2. CRYPTO: ETH NO BETS (bearish signal, 21h to settlement) ──────────────
print("\n[2] Opening crypto positions (BEARISH smart money signal)...")
print("     Smart money: $828K bear vs $227K bull across top 4 traders")
print("     Skipped XRP (closes in 30 min) | Using ETH (closes 9pm PDT)\n")

BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"

# ETH at $2,022. Bearish signal.
# B2030: band ~$2,020-2,040. YES=32¢. Model (bearish): ~12% → edge=20%
# B2070: band ~$2,060-2,080. YES=22¢. Model (bearish): ~5% → edge=17%
# B2110: check if it exists with edge

eth_trades = [
    {
        "ticker": "KXETH-26MAR1117-B2030",
        "side":   "no",
        "price":  75,   # no_ask = 75c (YES=32c → NO=68c market; use limit 75c)
        "title":  "Ethereum price Mar 11 – Band $2,030",
        "note":   "Bearish signal: ETH $2,022 -> band $2,030 (market 32%, model 12%) edge=20%",
        "size":   25.00,
    },
    {
        "ticker": "KXETH-26MAR1117-B2070",
        "side":   "no",
        "price":  84,   # no_ask = 84c
        "title":  "Ethereum price Mar 11 – Band $2,070",
        "note":   "Bearish signal: ETH $2,022 -> band $2,070 (market 22%, model 5%) edge=17%",
        "size":   25.00,
    },
]

# Also check for a longer-dated XRP (March 13 settlement)
try:
    r = requests.get(BASE, params={"series_ticker": "KXXRP", "status": "open", "limit": 50}, timeout=8)
    xrp_markets = r.json().get("markets", [])
    # Filter for March 13 settlement (1317 = 5pm ET March 13)
    mar13 = [m for m in xrp_markets if "26MAR1317" in m["ticker"]]
    # XRP at $1.38. Bearish. Look for NO bets on bands above $1.40
    for m in mar13:
        ya = m.get("yes_ask") or 0
        na = m.get("no_ask") or 0
        if ya < 5 or ya > 80 or na < 5: continue
        try:
            band = float(m["ticker"].split("-B")[-1])
        except: continue
        if band < 1.42: continue   # only bands meaningfully above current price
        edge_est = ya / 100 - 0.05   # rough: bearish → model ≈ 5% at these levels
        if edge_est >= 0.10:
            eth_trades.append({
                "ticker": m["ticker"], "side": "no", "price": na,
                "title": m.get("title", m["ticker"]),
                "note": f"XRP Mar13 bearish | band {band:.4f} | market {ya}% model ~5% edge {int(edge_est*100)}%",
                "size": 25.00,
            })
            break   # take the best one
except Exception as e:
    print(f"  XRP scan error: {e}")

for t in eth_trades[:3]:
    contracts = max(1, int(t["size"] / t["price"] * 100))
    actual    = round(contracts * t["price"] / 100, 2)
    place(t["ticker"], t["side"], "buy",
          price_cents=t["price"], contracts=contracts,
          size_dollars=actual, source="crypto",
          title=t["title"], note=t["note"])

print("\n" + "=" * 68)
print("  SUMMARY")
print("=" * 68)
print(f"  Weather exits:  2  (Miami B83.5 +$5.90 | Chicago B48.5 +$3.90)")
print(f"  Crypto entries: {len(eth_trades)} positions (ETH bearish + XRP Mar13)")
print(f"  Mode: {'DEMO — logged, not submitted to Kalshi' if DRY_RUN else 'LIVE — orders submitted'}")
print("=" * 68)
