"""Scan KXBTC/KXETH/KXXRP for edge using log-normal model + bearish smart money bias."""
import sys, requests, json, math, time
sys.stdout.reconfigure(encoding='utf-8')

BASE = "https://api.elections.kalshi.com/trade-api/v2/markets"
HDR  = {"User-Agent": "Mozilla/5.0"}

def norm_cdf(x):
    """Approx normal CDF without scipy."""
    t = 1 / (1 + 0.2316419 * abs(x))
    p = 1 - (0.319381530*t - 0.356563782*t**2 + 1.781477937*t**3
             - 1.821255978*t**4 + 1.330274429*t**5) * math.exp(-x*x/2) / math.sqrt(2*math.pi)
    return p if x >= 0 else 1 - p

def band_prob_lognormal(spot, band_mid, band_half_width, sigma, drift=0.0):
    mu = math.log(spot) + drift
    lo = band_mid - band_half_width
    hi = band_mid + band_half_width
    if lo <= 0: return 0.0
    p = norm_cdf((math.log(hi) - mu) / sigma) - norm_cdf((math.log(lo) - mu) / sigma)
    return max(0.0, min(1.0, p))

# Get live prices from Kraken
kr = requests.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,XRPUSD", timeout=6)
kd = kr.json().get("result", {})
prices = {}
for key, pair_key in [("btc", "XXBTZUSD"), ("eth", "XETHZUSD"), ("xrp", "XXRPZUSD")]:
    row = kd.get(pair_key) or kd.get(list(kd.keys())[list(kd.keys()).index(pair_key)] if pair_key in kd else "")
    if not row:
        # try alternative key format
        for k, v in kd.items():
            if key.upper() in k:
                row = v
                break
    if row:
        prices[key] = float(row["c"][0])

# Fallback individual calls
if "btc" not in prices:
    for sym, key in [("XBTUSD","btc"), ("ETHUSD","eth"), ("XRPUSD","xrp")]:
        try:
            r = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={sym}", timeout=5)
            prices[key] = float(list(r.json()["result"].values())[0]["c"][0])
        except: pass

BTC = prices.get("btc", 69827)
ETH = prices.get("eth", 2020)
XRP = prices.get("xrp", 1.38)
print(f"Prices: BTC=${BTC:,.0f}  ETH=${ETH:,.2f}  XRP=${XRP:.4f}")

# Bearish drift (smart money 78% bear → shift mean down 0.6 sigma)
BEARISH_DRIFT_SIGMA = -0.6

# Series config: (spot, band_half_width, daily_vol, hours_to_settle)
SERIES = {
    "KXBTC": (BTC, 250, 0.025, 18),
    "KXETH": (ETH, 10, 0.030, 18),
    "KXXRP": (XRP, 0.01, 0.045, 18),
}

all_opps = []

for series, (spot, half_w, daily_vol, hours) in SERIES.items():
    hourly_vol = daily_vol * math.sqrt(hours / 24)
    drift = BEARISH_DRIFT_SIGMA * hourly_vol  # shift log-mean

    r = requests.get(BASE, params={"series_ticker": series, "status": "open", "limit": 50}, timeout=8)
    markets = r.json().get("markets", [])

    for m in markets:
        yes_ask = m.get("yes_ask") or 0
        no_ask  = m.get("no_ask") or 0
        if yes_ask < 4 or yes_ask > 95 or no_ask < 4:
            continue
        try:
            band_mid = float(m["ticker"].split("-B")[-1])
        except:
            continue

        prob_bear = band_prob_lognormal(spot, band_mid, half_w, hourly_vol, drift)
        mkt_yes   = yes_ask / 100

        # Edge for NO bet: market overprices YES vs bearish model
        edge_no  = mkt_yes - prob_bear
        # Edge for YES bet: market underprices YES vs bearish model  
        edge_yes = prob_bear - mkt_yes

        if edge_no >= 0.10:
            all_opps.append({
                "action": "BUY NO", "series": series, "ticker": m["ticker"],
                "title": m.get("title",""), "band_mid": band_mid, "spot": spot,
                "yes_price": yes_ask, "no_price": no_ask,
                "model_pct": round(prob_bear*100,1), "mkt_pct": round(mkt_yes*100,1),
                "edge": round(edge_no, 3), "cost_per": no_ask,
            })
        elif edge_yes >= 0.10:
            all_opps.append({
                "action": "BUY YES", "series": series, "ticker": m["ticker"],
                "title": m.get("title",""), "band_mid": band_mid, "spot": spot,
                "yes_price": yes_ask, "no_price": no_ask,
                "model_pct": round(prob_bear*100,1), "mkt_pct": round(mkt_yes*100,1),
                "edge": round(edge_yes, 3), "cost_per": yes_ask,
            })

all_opps.sort(key=lambda x: x["edge"], reverse=True)
print(f"\nFound {len(all_opps)} crypto opportunities (edge >= 10%):\n")
for o in all_opps[:10]:
    dist = ((o["band_mid"] - o["spot"]) / o["spot"] * 100)
    print(f"  {o['action']:8} {o['ticker']:36} edge={o['edge']*100:.0f}%  model={o['model_pct']}% mkt={o['mkt_pct']}%  dist={dist:+.1f}%  cost={o['cost_per']}c")

# Save for execute script
import json
with open("logs/crypto_opps.json", "w", encoding="utf-8") as f:
    json.dump(all_opps[:10], f, indent=2)
print(f"\nTop opps saved to logs/crypto_opps.json")
