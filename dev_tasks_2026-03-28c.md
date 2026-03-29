# Dev Tasks — 2026-03-28c
_Issued by CEO. Two tasks — build in order. QA each before moving to next._

---

## Task 1: Dashboard WS Cache Integration

**Files:** `dashboard/api.py`

Replace all direct Kalshi REST price lookups with `market_cache.get_market_price()` + REST fallback. `market_cache.py` already exists and works.

### Helper to add to market_cache.py

```python
def get_market_price(ticker: str, fallback_client=None) -> dict | None:
    """
    Cache-first price lookup. Returns {bid, ask} in cent integers, or None.
    Falls back to REST via fallback_client if cache is stale/missing.
    """
    bid_d, ask_d, is_stale = get_with_staleness(ticker)
    if not is_stale and bid_d is not None:
        return {
            'yes_bid': round(bid_d * 100),
            'yes_ask': round(ask_d * 100),
            'no_bid':  round((1 - ask_d) * 100),
            'no_ask':  round((1 - bid_d) * 100),
            'source': 'ws_cache',
        }
    # Stale or missing — fall back to REST
    if fallback_client:
        try:
            market = fallback_client.get_market(ticker)
            if market:
                bid = market.get('yes_bid_dollars', 0)
                ask = market.get('yes_ask_dollars', 0)
                if bid and ask:
                    update(ticker, float(bid), float(ask), source='rest')
                return {
                    'yes_bid': round(float(bid) * 100) if bid else None,
                    'yes_ask': round(float(ask) * 100) if ask else None,
                    'no_bid':  round((1 - float(ask)) * 100) if ask else None,
                    'no_ask':  round((1 - float(bid)) * 100) if bid else None,
                    'source': 'rest',
                }
        except Exception:
            pass
    return None
```

### Endpoints to update in dashboard/api.py

Lines 391/416, 620/621, 640/641, 664/665, 698/699, 985/986, 1088/1089, 1289/1290, 1420/1421 — all direct `req.get(.../markets/{ticker}/orderbook)` or `req.get(.../markets/{ticker})` calls for live price data.

**Pattern:**
```python
# Before
ob_resp = req.get(f'https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook', timeout=4)
# ... parse orderbook ...

# After
import market_cache
prices = market_cache.get_market_price(ticker)
if prices is None:
    # fallback: still hit REST for settled/unavailable markets
    ob_resp = req.get(...)
    # ... existing parse logic ...
else:
    yes_ask = prices['yes_ask']
    yes_bid = prices['yes_bid']
```

**Do NOT change:**
- Line 248/249 — account balance (REST only)
- Line 491/492 — Kalshi positions (REST only)
- Lines 742/743, 863 — market discovery/listing (REST only)
- Lines 770/771 — resolved settlement prices (REST only, historical)
- Line 807 — Kraken prices (external API)

### QA
- [ ] Dashboard loads at http://192.168.4.31:8765
- [ ] Open positions show live prices (updating within 60s)
- [ ] Settled positions still show correct settlement prices
- [ ] No new Kalshi API calls for price lookups on open markets
- [ ] Cache source logged (`source: 'ws_cache'` vs `source: 'rest'`)

---

## Task 2: Long-Horizon Crypto Module (`crypto_long_horizon.py`)

New module for weekly/monthly/annual Kalshi crypto markets. DEMO only. Start with monthly and annual — skip weekly (too thin).

**Target series:**
- `KXBTCMAXM`, `KXBTCMAXY`, `KXBTCMINY`, `KXBTC2026250`, `KXBTCMAX100`
- `KXETHMAXM`, `KXETHMINY`, `KXETHMAXY`
- Skip DOGE/XRP long-horizon (manipulation risk)

---

### On-Chain Data Sources

**Fear & Greed Index (free, no auth):**
```python
def fetch_fear_greed() -> dict:
    """Returns {value: int, classification: str, trend_7d: float}"""
    resp = requests.get('https://api.alternative.me/fng/?limit=30', timeout=10)
    data = resp.json()['data']
    current = int(data[0]['value'])
    avg_7d = sum(int(d['value']) for d in data[:7]) / 7
    avg_30d = sum(int(d['value']) for d in data[:30]) / 30
    return {
        'value': current,
        'classification': data[0]['value_classification'],
        'avg_7d': round(avg_7d, 1),
        'avg_30d': round(avg_30d, 1),
        'trend': 'rising' if avg_7d > avg_30d else 'falling',
    }
```

**Regime Classifier (from F&G):**
```python
def classify_regime(fg: dict) -> str:
    """Returns 'bull' | 'neutral' | 'bear'"""
    v = fg['value']
    if v <= 25:   return 'bear'   # Extreme Fear / Fear
    elif v >= 75: return 'bull'   # Extreme Greed / Greed
    else:         return 'neutral'
```

---

### Price Model (Log-Normal with Regime Adjustment)

```python
from scipy.stats import norm
import math

def touch_probability(
    spot: float,
    strike: float,
    days_to_expiry: float,
    annualized_vol: float,
    regime: str,
) -> float:
    """
    P(BTC touches `strike` at least once before expiry).
    Uses log-normal with regime-adjusted vol + fat-tail correction.
    """
    # Regime vol multiplier
    vol_mult = {'bull': 1.2, 'neutral': 1.0, 'bear': 1.4}.get(regime, 1.0)
    sigma = annualized_vol * vol_mult * math.sqrt(days_to_expiry / 365)

    # Log-normal touch probability (one-sided)
    if strike > spot:
        # P(max price >= strike) — upper touch
        d = (math.log(spot / strike)) / sigma
        p = norm.cdf(d) + math.exp(2 * math.log(strike/spot) / sigma**2) * norm.cdf(-d - sigma)
        p = max(p, norm.cdf(-abs(math.log(strike/spot)) / sigma))
    else:
        # P(min price <= strike) — lower touch
        d = (math.log(spot / strike)) / sigma
        p = norm.cdf(-d) + math.exp(2 * math.log(strike/spot) / sigma**2) * norm.cdf(d - sigma)
        p = max(p, norm.cdf(-abs(math.log(strike/spot)) / sigma))

    # Fat-tail correction for extreme strikes (>2 sigma)
    z = abs(math.log(strike / spot)) / sigma
    if z > 2.0:
        fat_tail_boost = 1.35  # BTC fat tails ~35% more likely than log-normal suggests
        p = min(p * fat_tail_boost, 0.99)

    return round(p, 4)
```

Get `annualized_vol` from existing `crypto_client.py` signal data (realized vol is already computed there).

---

### Market Scanner

```python
def scan_long_horizon_markets(client: KalshiClient) -> list[dict]:
    """Fetch and evaluate all open long-horizon crypto markets."""
    opportunities = []
    capital = get_capital()
    fg = fetch_fear_greed()
    regime = classify_regime(fg)

    # Get spot prices (reuse existing crypto_client signals)
    from crypto_client import get_btc_signal, get_eth_signal
    btc_signal = get_btc_signal()
    eth_signal = get_eth_signal()
    prices = {'BTC': btc_signal['price'], 'ETH': eth_signal['price']}
    vols = {'BTC': btc_signal.get('realized_hourly_vol', 0.015) * math.sqrt(24*365),
            'ETH': eth_signal.get('realized_hourly_vol', 0.020) * math.sqrt(24*365)}

    TARGET_SERIES = ['KXBTCMAXM', 'KXBTCMAXY', 'KXBTCMINY', 'KXBTC2026250',
                     'KXBTCMAX100', 'KXETHMAXM', 'KXETHMINY', 'KXETHMAXY']

    for series in TARGET_SERIES:
        asset = 'ETH' if 'ETH' in series else 'BTC'
        spot = prices[asset]
        vol = vols[asset]

        markets = client.get_markets(series_ticker=series, status='open', limit=10)
        for m in markets:
            ticker = m.get('ticker', '')
            close_time = m.get('close_time', '')
            if not close_time:
                continue

            # Days to expiry
            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            days = max((close_dt - datetime.now(timezone.utc)).days, 1)

            # Parse strike from ticker
            strike = parse_strike(ticker)  # extract numeric strike from ticker
            if not strike:
                continue

            # Model probability
            model_prob = touch_probability(spot, strike, days, vol, regime)

            # Market price from WS cache
            prices_cached = market_cache.get_market_price(ticker)
            if prices_cached:
                yes_ask = prices_cached['yes_ask']
                yes_bid = prices_cached['yes_bid']
            else:
                # REST fallback
                raw = client.get_market(ticker)
                yes_ask = round(float(raw.get('yes_ask_dollars', 0.5)) * 100)
                yes_bid = round(float(raw.get('yes_bid_dollars', 0.4)) * 100)

            if not yes_ask:
                continue

            # Edge calculation
            market_prob = yes_ask / 100
            edge = model_prob - market_prob
            side = 'yes' if edge > 0 else 'no'
            if abs(edge) < config.LONG_HORIZON_MIN_EDGE:
                continue

            # Spread filter
            spread = yes_ask - yes_bid
            if spread > config.LONG_HORIZON_MAX_SPREAD:
                continue

            opportunities.append({
                'ticker': ticker,
                'asset': asset,
                'strike': strike,
                'days_to_expiry': days,
                'spot': spot,
                'model_prob': model_prob,
                'market_prob': market_prob,
                'edge': round(edge, 4),
                'side': side,
                'yes_ask': yes_ask,
                'yes_bid': yes_bid,
                'spread': spread,
                'regime': regime,
                'fear_greed': fg['value'],
                'fear_greed_trend': fg['trend'],
                'series': series,
            })

    return sorted(opportunities, key=lambda x: abs(x['edge']), reverse=True)
```

---

### Position Sizing (Long-Horizon specific)

Long-horizon positions are held for days/weeks — different sizing logic:

```python
def size_long_horizon(edge: float, win_prob: float, capital: float, days: int) -> float:
    """More conservative sizing for long-duration holds."""
    c = win_prob - edge  # approximate entry price
    kelly = (win_prob - c) / (c * (1 - c)) if c > 0 else 0
    # More conservative: 1/6 Kelly for long horizon (vs 1/4 for intraday)
    sized = (kelly / 6) * capital
    # Hard caps
    max_pos = capital * config.LONG_HORIZON_MAX_POSITION_PCT
    return round(min(sized, max_pos, 50.0), 2)  # $50 max per long-horizon trade
```

---

### Config additions

```python
LONG_HORIZON_MIN_EDGE = 0.08        # 8c minimum edge
LONG_HORIZON_MAX_SPREAD = 10        # max 10c spread (monthly/annual are tighter)
LONG_HORIZON_MAX_POSITION_PCT = 0.005  # 0.5% of capital per trade
LONG_HORIZON_DAILY_CAP_PCT = 0.10   # 10% of capital/day total for this module
```

---

### Exit Logic

Long-horizon positions exit on:
1. **95c rule** — same as other modules (position_tracker handles this via WS)
2. **Settlement** — market expires, Kalshi auto-settles
3. **Manual override** — David says exit

Do NOT apply 70% gain exit for long-horizon positions (price has days/weeks to move). Add `holding_type='long_horizon'` to position_tracker entries to skip the 70% gain threshold.

---

### Scan Schedule

Add to `ruppert_cycle.py`:
- Run `long_horizon_scan` once per day at 7AM (inside full cycle)
- Skip if daily long-horizon cap already hit

---

### WS Subscription

Add to `config.py` `WS_ACTIVE_SERIES`:
```python
'KXBTCMAXM', 'KXBTCMAXY', 'KXBTCMINY', 'KXBTC2026250', 'KXBTCMAX100',
'KXETHMAXM', 'KXETHMINY', 'KXETHMAXY',
```

These will now get live price updates via the WS feed automatically.

---

### Decision Logging

Log all evaluations (including no-trades) to `logs/decisions_long_horizon.jsonl`:
```json
{
  "ts": "ISO8601",
  "ticker": "KXBTCMAXY-...",
  "asset": "BTC",
  "strike": 150000,
  "days_to_expiry": 278,
  "spot": 87500,
  "model_prob": 0.34,
  "market_prob": 0.28,
  "edge": 0.06,
  "regime": "bear",
  "fear_greed": 12,
  "fear_greed_trend": "falling",
  "decision": "SKIP",
  "skip_reason": "insufficient_edge",
  "position_usd": null
}
```

---

## QA Checklist (Task 2)

- [ ] `crypto_long_horizon.py` passes `ast.parse`
- [ ] `fetch_fear_greed()` returns valid data from alternative.me API
- [ ] `touch_probability()` returns sensible values (test: BTC=$87k, strike=$100k, 90 days, vol=0.8 → should be ~35-45%)
- [ ] `scan_long_horizon_markets()` runs without error, returns list
- [ ] Decision log writes correctly including SKIP entries
- [ ] Position sizing: $50 hard cap respected
- [ ] Long-horizon positions in position_tracker skip the 70% gain exit
- [ ] WS series list updated in config.py
- [ ] 7AM full cycle now includes long_horizon_scan
- [ ] DRY_RUN respected throughout
- [ ] Commit and push
