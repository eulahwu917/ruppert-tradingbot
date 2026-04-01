# Polymarket Signal Client — Implementation Spec

**File:** `agents/ruppert/data_analyst/polymarket_client.py`  
**Status:** Ready for Dev  
**Author:** DS — 2026-03-31  
**Scope:** READ-ONLY signal layer. No trading. No auth required.

---

## Overview

Shared client module that pulls Polymarket market prices, live CLOB midpoints, and smart money wallet positions. Used as an additional signal source by:

- `crypto_client.py` / `crypto_15m.py` → `get_crypto_consensus`, `get_smart_money_signal`
- `geopolitical_scanner.py` → `get_geo_signals`
- `sports_odds_collector.py` → `get_markets_by_keyword`

---

## Dependencies

```
requests  (already in project)
```

No Polymarket SDK. Raw HTTP only.

---

## API Endpoints

```python
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"
DATA_BASE  = "https://data-api.polymarket.com"
```

All requests: `timeout=10s`, no auth headers required.

---

## Cache Design

Module-level dict `_cache = {}`.  
Structure: `{ key: (value, expires_at_epoch_float) }`

```python
def _cached(key: str, fn, ttl_seconds: int):
    now = time.time()
    if key in _cache:
        value, expires_at = _cache[key]
        if now < expires_at:
            return value
    value = fn()
    _cache[key] = (value, now + ttl_seconds)
    return value
```

Cache is in-process only (no Redis, no disk). Resets on process restart. That's fine.

---

## Function Contracts

### `get_markets_by_keyword(keyword, limit=20) → list[dict]`

**Endpoint:** `GET {GAMMA_BASE}/public-search?q=<keyword>&limit=<n>`

**Response parsing:**
```
data["events"]  →  list of event objects
event.active == True and not event.closed  →  keep
event.markets  →  list of market objects
market.closed == True  →  skip
market.outcomePrices  →  JSON string: '["0.385", "0.615"]'  →  index[0] = YES price
market.clobTokenIds   →  JSON string: '["<YES_id>", "<NO_id>"]'  →  index[0] = YES token
market.volume24hr     →  24h volume float
market.endDate / endDateIso  →  end date string
```

**Returns per market:**
```python
{
    "question":       str,
    "yes_price":      float | None,   # 0-1
    "volume_24h":     float,
    "end_date":       str | None,
    "clob_yes_token": str | None,
    "last_trade":     float,
}
```

**Cache key:** `f"markets:{keyword}:{limit}"` — TTL: **5 minutes**  
**On error:** return `[]`, log warning

---

### `get_live_price(clob_token_id) → float | None`

**Endpoint:** `GET {CLOB_BASE}/midpoint?token_id=<id>`  
**Response:** `{"mid": 0.385}`  
**Returns:** `float` in [0, 1], or `None` on error  
**No cache** — always fresh  
**On error:** return `None`, log warning

---

### `get_wallet_positions(wallet_address) → list[dict]`

**Endpoint:** `GET {DATA_BASE}/positions?user=<wallet>&limit=50`

**Response array fields:**
```
title, outcome, size, curPrice, cashPnl, percentPnl, avgPrice, endDate
```

**Returns per position:**
```python
{
    "title":     str,
    "outcome":   str,          # "YES" or "NO"
    "yes_price": float,        # curPrice
    "size":      float,
    "cash_pnl":  float,
    "pct_pnl":   float,
    "avg_price": float,
    "end_date":  str | None,
}
```

**Cache key:** `f"wallet:{wallet_address}"` — TTL: **10 minutes**  
**On error:** return `[]`, log warning

---

### `get_smart_money_signal(wallet_addresses, keyword) → dict`

Calls `get_wallet_positions` for each wallet (uses cache). Matches positions whose title contains `keyword` (case-insensitive). Counts YES vs NO outcomes.

**Returns:**
```python
{
    "yes_count":       int,    # wallets with YES position in matched markets
    "no_count":        int,    # wallets with NO position in matched markets
    "net_signal":      float,  # (yes_count - no_count) / total; 0.0 if no positions
    "wallets_checked": int,
    "markets_matched": list[str],   # sorted unique market titles
}
```

**On error:** return zeroed dict (never raises)  
No additional cache — relies on `get_wallet_positions` cache

---

### `get_crypto_consensus(asset) → dict | None`

**Supported assets:** `BTC`, `ETH`, `XRP`, `DOGE`, `SOL`

**Search strategy:**
1. Iterate keyword list for asset (e.g. `["bitcoin up", "btc up", "bitcoin 15min", ...]`)
2. For each keyword, call `get_markets_by_keyword` (5-min cache)
3. Filter: title must contain asset name AND a directional term (`up/down/higher/lower/above/below/rise/fall`)
4. Score candidates: +10 if title contains short-window term (`15min`, `1hr`, `30min`, etc.), +1 if `volume_24h > 1000`
5. Return the highest-scored candidate

**Returns:**
```python
{
    "asset":        str,    # normalised e.g. "BTC"
    "yes_price":    float,  # probability of UP (0-1)
    "market_title": str,
    "volume_24h":   float,
    "source":       "polymarket",
}
```

**Cache key:** `f"crypto_consensus:{asset.upper()}"` — TTL: **5 minutes**  
**Returns `None`** if no matching market found or on error

---

### `get_geo_signals(keywords=None) → list[dict]`

**Default keywords:** `['ceasefire', 'war', 'invasion', 'sanctions', 'conflict', 'nuclear']`

Calls `get_markets_by_keyword` for each keyword (5-min cache per keyword). Deduplicates by question text.

**Returns per market:**
```python
{
    "question":  str,
    "yes_price": float | None,
    "volume_24h": float,
    "end_date":  str | None,
    "category":  "geo",
}
```

**Cache key:** `f"geo_signals:{','.join(sorted(keywords))}"` — TTL: **10 minutes**  
**On error:** return `[]`, log warning

---

## Error Handling Rules

| Condition | Behaviour |
|---|---|
| Network error / timeout | `logger.warning(...)`, return `[]` or `None` |
| HTTP non-200 | Same — `raise_for_status()` caught by outer try/except |
| Malformed JSON field | Skip that market/position, continue |
| Unknown asset in `get_crypto_consensus` | `logger.warning(...)`, return `None` |
| Any uncaught exception | Caught at function boundary, return safe default |

**Never let exceptions propagate to callers.**

---

## Integration Snippets

### crypto_client.py
```python
from agents.ruppert.data_analyst.polymarket_client import get_crypto_consensus

poly = get_crypto_consensus('BTC')
if poly:
    polymarket_bias = poly['yes_price']  # 0-1 probability of UP
```

### geopolitical_scanner.py
```python
from agents.ruppert.data_analyst.polymarket_client import get_geo_signals

geo = get_geo_signals(['ceasefire', 'war', 'sanctions'])
# yes_price > 0.7 on conflict markets → elevated geo risk
```

### sports_odds_collector.py
```python
from agents.ruppert.data_analyst.polymarket_client import get_markets_by_keyword

sports = get_markets_by_keyword('NBA winner tonight')
# Cross-reference yes_price with Kalshi NBA markets for gap detection
```

---

## Acceptance Criteria

- [ ] All 6 functions implemented and return correct types
- [ ] In-process TTL cache working (5 or 10 min depending on function)
- [ ] `get_crypto_consensus('BTC')` returns a dict with `yes_price` when called
- [ ] `get_wallet_positions('0xde17f7144fbd0eddb2679132c10ff5e74b120988')` returns a list
- [ ] `get_smart_money_signal(wallets, 'bitcoin')` returns `net_signal` in [-1, 1]
- [ ] No exceptions propagate — all functions return `None`/`[]` on error
- [ ] Quick smoke test passes:
  ```
  python -c "from agents.ruppert.data_analyst.polymarket_client import get_crypto_consensus; print(get_crypto_consensus('BTC'))"
  ```
- [ ] Commit: `feat: polymarket_client.py - shared signal layer for crypto/geo/sports`

---

## Out of Scope (this ticket)

- Integration into `crypto_15m.py` or other modules → separate task post-Optimizer review
- Signal weighting → Optimizer's call
- Writing to any position or order → geo-locked, never
- Persistence / Redis caching → not needed at current polling frequency

---

**DS**
