# Polymarket Wiring Spec — 2026-04-01

## Status: Draft
## Author: Data Scientist agent

---

## 1. Crypto 15m: Replace `get_polymarket_yes_prob` Stub

**Current state:** `crypto_15m.py:525-531` — stub returns `None`, disabling the Polymarket divergence nudge entirely.

**Wiring:**
- Import `get_crypto_consensus` from `agents.ruppert.data_analyst.polymarket_client`
- Replace stub body:

```python
def get_polymarket_yes_prob(asset: str) -> float | None:
    from agents.ruppert.data_analyst.polymarket_client import get_crypto_consensus
    result = get_crypto_consensus(asset)   # 5-min cache, returns {asset, yes_price, market_title, volume_24h, source}
    if result is None:
        return None
    return result['yes_price']             # float in [0, 1]
```

**Params:** `asset` — one of BTC, ETH, XRP, DOGE, SOL (already the format `get_crypto_consensus` expects).

**Weight:** The existing nudge logic at lines 968-992 already handles weighting:
- `CRYPTO_15M_POLY_DIVERGENCE_THRESHOLD` (default 0.03) — minimum divergence to trigger nudge
- `CRYPTO_15M_POLY_NUDGE_WEIGHT` (default 0.3) — nudge magnitude as fraction of divergence
- Formula: `poly_nudge = 0.3 * (poly_yes - kalshi_yes)` when `|divergence| > 0.03`
- No config changes needed; existing defaults are reasonable for initial deployment.

**Risk:** `get_crypto_consensus` prefers 15min/1hr windows — good fit. 5-min cache prevents excessive API calls. Graceful `None` fallback already handled.

---

## 2. Geo: Wire `get_geo_signals()` + TheNewsAPI into `geo_client.py`

**Current state:** `geo_client.py` uses GDELT v2 DOC API only. No Polymarket or TheNewsAPI integration.

**Wiring plan:**

### 2a. Polymarket geo signals
- Import `get_geo_signals` from `agents.ruppert.data_analyst.polymarket_client`
- `get_geo_signals(keywords)` returns `[{question, yes_price, volume_24h, end_date, category='geo'}]` with 10-min cache
- Add a new function `get_combined_geo_events()` that merges GDELT events with Polymarket geo signals

### 2b. TheNewsAPI integration
- API key: `RGPtfv3i6ni4bucrlfpUrMuDUMmRuvi9fGubxwmt`
- Endpoint: `https://api.thenewsapi.com/v1/news/all`
- Params: `api_token`, `search` (geo keywords), `language=en`, `limit=25`
- Add `get_thenewsapi_events(query, limit=25)` returning `[{title, url, source, published_at, snippet}]`

### 2c. Signal weighting vs GDELT
| Source | Weight | Rationale |
|--------|--------|-----------|
| GDELT | 0.40 | Broadest coverage, ~15min refresh, free, but noisy |
| Polymarket | 0.35 | Market-implied probability = skin-in-the-game signal; volume_24h as confidence proxy |
| TheNewsAPI | 0.25 | Curated feed, lower latency than GDELT, but narrower coverage |

- Combined severity score: `severity = 0.40 * gdelt_severity + 0.35 * poly_yes_price + 0.25 * news_relevance_score`
- Polymarket `yes_price` directly encodes probability → use as-is for severity component
- GDELT severity from existing `_parse_event()` logic (0-1 scale)
- TheNewsAPI relevance: keyword density match (0-1 scale)

---

## 3. Crypto 1h / 1d: Feasibility

- **Crypto 1h:** `get_crypto_consensus` already prefers 15min/1hr windows — can reuse the same call with no changes; feasible and recommended.
- **Crypto 1d:** Polymarket daily crypto markets are sparse and illiquid; skip integration for now — MACD/OI signals are more reliable at daily timeframes.

---

## 4. Weather

**Skip.** Polymarket has no active weather-outcome markets (checked via `get_markets_by_keyword('weather')`). Weather module should continue using direct API sources (OpenWeatherMap, NOAA).
