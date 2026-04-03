# Polymarket Shadow Logging — All Crypto Modules
**Author:** Strategist
**Date:** 2026-04-01
**Status:** Implementation-ready
**Scope:** Shadow logging only. Zero weight changes. Zero decision logic changes.
**Depends on:** DS spec `specs/polymarket-shadow-logging-spec.md` (Module 1 / crypto_15m section)

---

## Executive Summary

The DS spec (2026-03-31) covers crypto_15m shadow logging thoroughly. This spec extends Polymarket shadow data collection to the **daily crypto modules**:

| Module type | Module IDs | File | Log file |
|-------------|-----------|------|----------|
| 15m direction | `crypto_dir_15m_{btc,eth,sol,xrp,doge}` | `agents/ruppert/trader/crypto_15m.py` | `decisions_15m.jsonl` |
| Daily threshold | `crypto_threshold_daily_{btc,eth,sol}` | `agents/ruppert/trader/crypto_1d.py` | `decisions_1d.jsonl` |
| Daily band | `crypto_band_daily_{btc,eth}` | `agents/ruppert/trader/main.py` | trade log (via `execute_opportunity`) |

---

## Part A: DS Spec Review (crypto_15m)

The DS spec for Module 1 (crypto_15m.py) is **correct and complete**. Three minor observations, none blocking:

1. **Staleness guard is conservative but sound.** The 10-min threshold on a 5-min-cached value means it only fires on cold-cache + stale fetch. This is the right behavior — no change needed.

2. **`import time as _time` at function scope** — DS correctly notes this is idempotent. Dev should move it to module-level for consistency with the rest of the file (`import time` already exists at line 25). Cosmetic only.

3. **`get_polymarket_yes_prob` removal** — The DS spec removes the stub and replaces it with `get_crypto_consensus`. This is correct. The stub currently returns `None` always, so the divergence nudge block is dead code. After the DS spec lands, it will be live with real data. **No behavioral change** until Polymarket actually has matching 15m markets (which is the point — shadow collect first).

**Verdict: DS spec Module 1 is approved as-is. Dev can implement directly.**

---

## Part B: Daily Threshold Module (crypto_1d.py)

### B0. Current state

`crypto_1d.py` **already has Polymarket wired as Signal S5** (lines 483–508). The function `compute_s5_polymarket(asset)` calls `get_crypto_consensus(asset)` and returns `{yes_price, raw_score, available, market_title, volume_24h}`. This signal is blended at 20% weight into the composite score when available.

This means **crypto_1d already uses Polymarket for live decisions, not just shadow logging.** However, the S5 data is only partially logged — it flows into the composite score but the raw Polymarket fields are not individually persisted in `decisions_1d.jsonl`.

### B1. What's missing: raw Polymarket fields in `decisions_1d.jsonl`

The `_log_decision` function (line 815) logs `S1–S4` signal details but **does not log S5 (Polymarket) fields**. The composite score is logged, which bakes in the Polymarket weight, but we can't retroactively analyze the Polymarket signal quality without the raw fields.

### B2. Why daily modules need different Polymarket data than 15m

`get_crypto_consensus()` in `polymarket_client.py` is biased toward **short-window markets** (see `_SHORT_WINDOW_TERMS` at line 282: "15min", "1hr", etc.). It scores these 10 points higher. For a daily threshold module settling at 17:00 ET (~8–24 hours from entry), the ideal Polymarket market is:

- A **daily or longer-horizon** price target market (e.g., "Will BTC be above $X by end of day?")
- NOT a 15-minute directional market

However, Polymarket's crypto offerings are sparse and unpredictable. The pragmatic approach:

1. **Use `get_crypto_consensus()` as-is for now** — even a short-window market consensus provides useful directional signal for shadow analysis. If the 15m market says 70% YES for UP, that's a data point for the daily module too.
2. **Add a new `get_crypto_daily_consensus()` function** to `polymarket_client.py` that prefers longer-horizon markets (daily, weekly) when available, falling back to `get_crypto_consensus()` when not.
3. **Log both** — the short-window consensus (already fetched by S5) and the daily consensus (new fetch) — so we can compare signal quality in the correlation analysis.

### B3. New function: `get_crypto_daily_consensus()` in polymarket_client.py

**File:** `agents/ruppert/data_analyst/polymarket_client.py`

Add after `get_crypto_consensus()` (after line 365):

```python
# Daily/long-horizon crypto keywords
_CRYPTO_DAILY_KEYWORDS: dict[str, list[str]] = {
    "BTC": ["bitcoin daily", "btc end of day", "bitcoin price today", "btc above", "btc below"],
    "ETH": ["ethereum daily", "eth end of day", "ethereum price today", "eth above", "eth below"],
    "SOL": ["solana daily", "sol end of day", "solana price today", "sol above", "sol below"],
}

# Long-window preference: score higher for daily/weekly terms in market title
_LONG_WINDOW_TERMS = ["daily", "end of day", "eod", "24h", "24 hour", "today", "this week", "weekly"]


def _score_crypto_daily_market(market: dict) -> int:
    """Higher score = preferred market (long-window, high volume)."""
    title_lower = (market.get("question") or "").lower()
    score = 0
    for term in _LONG_WINDOW_TERMS:
        if term in title_lower:
            score += 10
            break
    # Penalize short-window markets
    for term in _SHORT_WINDOW_TERMS:
        if term in title_lower:
            score -= 5
            break
    if market.get("volume_24h", 0) > 1000:
        score += 1
    return score


def _fetch_crypto_daily_consensus(asset: str) -> Optional[dict]:
    """Raw fetch for get_crypto_daily_consensus — not cached directly."""
    asset = asset.upper()
    keywords = _CRYPTO_DAILY_KEYWORDS.get(asset)
    if not keywords:
        # Fallback to short-window function
        return _fetch_crypto_consensus(asset)

    candidates = []
    for kw in keywords:
        markets = get_markets_by_keyword(kw, limit=10)
        for m in markets:
            q_lower = (m.get("question") or "").lower()
            asset_lower = asset.lower()
            if asset_lower not in q_lower:
                continue
            directional_terms = ["up", "down", "higher", "lower", "above", "below", "rise", "fall"]
            if not any(t in q_lower for t in directional_terms):
                continue
            if m.get("yes_price") is None:
                continue
            candidates.append(m)

    if not candidates:
        # No daily markets found — fall back to short-window consensus
        return _fetch_crypto_consensus(asset)

    best = max(candidates, key=_score_crypto_daily_market)

    return {
        "asset":        asset,
        "yes_price":    best["yes_price"],
        "market_title": best["question"],
        "volume_24h":   best.get("volume_24h", 0.0),
        "source":       "polymarket",
        "horizon":      "daily",
    }


def get_crypto_daily_consensus(asset: str) -> Optional[dict]:
    """
    Get Polymarket consensus price for a crypto asset daily direction.

    Prefers daily/EOD markets. Falls back to short-window consensus if no
    daily market exists.

    asset: 'BTC' | 'ETH' | 'SOL'

    Returns:
        asset         str   — normalised asset symbol
        yes_price     float — probability of UP/ABOVE (0-1)
        market_title  str   — matched market question
        volume_24h    float — 24-hour volume
        source        str   — 'polymarket'
        horizon       str   — 'daily' if daily market found, absent if fallback

    Returns None if no relevant market found or on error.
    Cache: 10 minutes (longer than 15m — daily markets don't need sub-5min freshness).
    """
    cache_key = f"crypto_daily_consensus:{asset.upper()}"
    try:
        return _cached(
            cache_key,
            lambda: _fetch_crypto_daily_consensus(asset),
            ttl_seconds=600,  # 10 minutes
        )
    except Exception as exc:
        logger.warning("polymarket get_crypto_daily_consensus('%s') failed: %s", asset, exc)
        return None
```

### B4. Changes to `crypto_1d.py`

**File:** `agents/ruppert/trader/crypto_1d.py`

#### B4a. Add import

After the existing imports (line 38 area), add:

```python
from agents.ruppert.data_analyst.polymarket_client import get_crypto_daily_consensus
```

#### B4b. Extend `_log_decision` to include S5 Polymarket fields

**Current signature (line 815):**
```python
def _log_decision(asset: str, window: str, signals: dict, decision: str, reason: str,
                  market_id: str = None, size_usd: float = None,
                  composite: float = None, P_above: float = None, edge: float = None):
```

**New signature — add keyword args:**
```python
def _log_decision(asset: str, window: str, signals: dict, decision: str, reason: str,
                  market_id: str = None, size_usd: float = None,
                  composite: float = None, P_above: float = None, edge: float = None,
                  poly_yes_price: float = None,
                  poly_market_title: str = None,
                  poly_volume_24h: float = None,
                  poly_fetched_at: str = None,
                  poly_daily_yes_price: float = None,
                  poly_daily_market_title: str = None,
                  poly_daily_fetched_at: str = None):
```

#### B4c. Add Polymarket fields to the entry dict inside `_log_decision`

After the existing `if edge is not None:` block (line 852), add:

```python
    # Shadow: Polymarket fields
    entry['poly_yes_price']          = poly_yes_price
    entry['poly_market_title']       = poly_market_title
    entry['poly_volume_24h']         = poly_volume_24h
    entry['poly_fetched_at']         = poly_fetched_at
    entry['poly_daily_yes_price']    = poly_daily_yes_price
    entry['poly_daily_market_title'] = poly_daily_market_title
    entry['poly_daily_fetched_at']   = poly_daily_fetched_at
```

#### B4d. Fetch daily consensus in `evaluate_crypto_1d_entry`

**Location:** After `s5 = compute_s5_polymarket(asset)` (line 965) and before `signals_dict = {...}` (line 967).

```python
    # ── Shadow: Polymarket daily consensus (logging only) ──
    _poly_daily_result = None
    _poly_daily_fetched_at = None
    try:
        _poly_daily_result = get_crypto_daily_consensus(asset)
        if _poly_daily_result:
            _poly_daily_fetched_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception:
        pass
    # ── End Polymarket daily shadow ──
```

#### B4e. Update all `_log_decision` calls to pass Polymarket fields

There are multiple call sites. For every `_log_decision(...)` call in `evaluate_crypto_1d_entry` and `_skip`, add the Polymarket kwargs.

**In `_skip()` (line 871):** Update to accept and forward Polymarket fields. Change signature:

```python
def _skip(asset, window, reason, signals=None,
          poly_yes_price=None, poly_market_title=None, poly_volume_24h=None,
          poly_fetched_at=None, poly_daily_yes_price=None,
          poly_daily_market_title=None, poly_daily_fetched_at=None):
```

And forward to `_log_decision`:
```python
    _log_decision(asset, window, signals or {}, 'SKIP', reason,
                  poly_yes_price=poly_yes_price,
                  poly_market_title=poly_market_title,
                  poly_volume_24h=poly_volume_24h,
                  poly_fetched_at=poly_fetched_at,
                  poly_daily_yes_price=poly_daily_yes_price,
                  poly_daily_market_title=poly_daily_market_title,
                  poly_daily_fetched_at=poly_daily_fetched_at)
```

**Important:** Only the `_skip` and `_log_decision` calls that fire **after** signal computation (line 965+) should pass non-None Polymarket values. Early skips (before signals) will pass `None` via defaults — this is correct behavior.

**For the ENTER path (line 1076):** Add to the existing `_log_decision` call:

```python
    _log_decision(
        asset=asset, window=window, signals=signals_dict,
        decision='ENTER', market_id=market_id, size_usd=actual_cost,
        composite=composite['raw_composite'], P_above=composite['P_above'],
        edge=best.get('edge'),
        reason=(...),
        poly_yes_price=s5.get('yes_price') if s5 else None,
        poly_market_title=s5.get('market_title') if s5 else None,
        poly_volume_24h=s5.get('volume_24h') if s5 else None,
        poly_fetched_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if s5 and s5.get('available') else None,
        poly_daily_yes_price=_poly_daily_result.get('yes_price') if _poly_daily_result else None,
        poly_daily_market_title=_poly_daily_result.get('market_title') if _poly_daily_result else None,
        poly_daily_fetched_at=_poly_daily_fetched_at,
    )
```

**For the insufficient_edge SKIP (line 999):** Same pattern — add the poly kwargs.

**For all `_skip()` calls after signal computation (lines 971, 976, 981):** Pass the poly fields:

```python
    return _skip(asset, window, 'R6_extreme_funding', signals_dict,
                 poly_yes_price=s5.get('yes_price') if s5 else None,
                 poly_market_title=s5.get('market_title') if s5 else None,
                 poly_volume_24h=s5.get('volume_24h') if s5 else None,
                 poly_fetched_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if s5 and s5.get('available') else None,
                 poly_daily_yes_price=_poly_daily_result.get('yes_price') if _poly_daily_result else None,
                 poly_daily_market_title=_poly_daily_result.get('market_title') if _poly_daily_result else None,
                 poly_daily_fetched_at=_poly_daily_fetched_at)
```

### B5. Fields added to `decisions_1d.jsonl`

| Field | Type | Notes |
|-------|------|-------|
| `poly_yes_price` | `float \| null` | S5 short-window Polymarket YES price (0-1). Already used in composite but not logged individually |
| `poly_market_title` | `str \| null` | Matched short-window market question |
| `poly_volume_24h` | `float \| null` | 24h volume of matched short-window market |
| `poly_fetched_at` | `str \| null` | ISO 8601 UTC fetch timestamp |
| `poly_daily_yes_price` | `float \| null` | Daily-horizon Polymarket YES price (0-1). New fetch via `get_crypto_daily_consensus` |
| `poly_daily_market_title` | `str \| null` | Matched daily market question |
| `poly_daily_fetched_at` | `str \| null` | ISO 8601 UTC fetch timestamp for daily market |

---

## Part C: Daily Band Module (main.py)

### C0. Current state

The band module in `main.py` (lines ~500–740) trades `KXBTC`/`KXETH` above/below band markets. It does **not** call any Polymarket function. It does **not** use `_log_decision` — trade decisions are logged via `execute_opportunity()` which writes to the main trade log, not a dedicated decisions JSONL.

Module IDs: `crypto_band_daily_btc`, `crypto_band_daily_eth`.

### C1. Design decision: where to log Polymarket data for band module

The band module has no dedicated decisions log. Options:

1. **Add Polymarket fields to the `opp` dict passed to `execute_opportunity()`** — This is the lightest-touch approach. The trade logger already persists all `opp` fields. Shadow fields would appear in the trade log alongside executed trades.
2. **Create a new `decisions_band.jsonl`** — Overkill for shadow logging.
3. **Log to `log_activity()`** — Not structured, not queryable.

**Recommendation: Option 1.** Add Polymarket fields directly to the `opp` dict constructed at line 701 in `main.py`. This is the same pattern the band module already uses for all its data — no new logging infrastructure needed.

### C2. Changes to `main.py`

**File:** `agents/ruppert/trader/main.py`

#### C2a. Add import

Near the top of the file, in the imports section:

```python
from agents.ruppert.data_analyst.polymarket_client import get_crypto_daily_consensus
```

#### C2b. Fetch Polymarket data before the band trade loop

**Location:** Inside the crypto band scanning section, after `new_crypto.sort(...)` (line 600) and before the daily cap check block (line 603). Insert:

```python
        # ── Shadow: Polymarket daily consensus for band module (logging only) ──
        _band_poly_cache = {}  # {asset: {yes_price, market_title, volume_24h, fetched_at}}
        for _bp_asset in ('BTC', 'ETH'):
            try:
                _bp_result = get_crypto_daily_consensus(_bp_asset)
                if _bp_result:
                    _band_poly_cache[_bp_asset] = {
                        'yes_price':    _bp_result.get('yes_price'),
                        'market_title': _bp_result.get('market_title'),
                        'volume_24h':   _bp_result.get('volume_24h'),
                        'fetched_at':   datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    }
            except Exception:
                pass
        # ── End Polymarket shadow ──
```

#### C2c. Add Polymarket fields to the `opp` dict

**Location:** In the `opp = { ... }` dict constructed at line 701, add after the existing fields:

```python
            # Determine which asset this trade is for
            _band_asset = 'BTC' if 'BTC' in t.get('series', '') else 'ETH'
            _bp_data = _band_poly_cache.get(_band_asset, {})

            opp = {
                'ticker': t['ticker'], 'title': t['title'], 'side': t['side'],
                'action': 'buy', 'yes_price': t['price'] if t['side'] == 'yes' else 100 - t['price'],
                'market_prob': t['price'] / 100, 'noaa_prob': None,
                'edge': t['edge'], 'confidence': t.get('confidence', t['edge']),
                'size_dollars': actual_cost,
                'contracts': contracts, 'source': 'crypto',
                'scan_price': t['price'],
                'fill_price': t['price'],
                'scan_contracts': contracts,
                'fill_contracts': contracts,
                'note': t['note'],
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'date': str(date.today()),
                # Shadow: Polymarket daily consensus
                'poly_daily_yes_price':    _bp_data.get('yes_price'),
                'poly_daily_market_title': _bp_data.get('market_title'),
                'poly_daily_volume_24h':   _bp_data.get('volume_24h'),
                'poly_daily_fetched_at':   _bp_data.get('fetched_at'),
            }
```

### C3. Fields added to trade log entries (band module)

| Field | Type | Notes |
|-------|------|-------|
| `poly_daily_yes_price` | `float \| null` | Daily-horizon Polymarket YES price (0-1) |
| `poly_daily_market_title` | `str \| null` | Matched daily market question |
| `poly_daily_volume_24h` | `float \| null` | 24h volume |
| `poly_daily_fetched_at` | `str \| null` | ISO 8601 UTC |

Note: Band module does NOT get the short-window `poly_yes_price` field. The band module trades longer-horizon markets (multi-hour to daily), so the short-window (15m/1hr) consensus price is not relevant. Only the daily consensus is logged.

---

## Part D: Summary of All File Changes

| # | File | What changes |
|---|------|-------------|
| 1 | `agents/ruppert/data_analyst/polymarket_client.py` | Add `get_crypto_daily_consensus()`, `_fetch_crypto_daily_consensus()`, `_score_crypto_daily_market()`, `_CRYPTO_DAILY_KEYWORDS`, `_LONG_WINDOW_TERMS` |
| 2 | `agents/ruppert/trader/crypto_1d.py` | Add import, extend `_log_decision` signature with 7 poly kwargs, extend `_skip` signature, add daily consensus fetch in `evaluate_crypto_1d_entry`, pass poly fields to all post-signal `_log_decision`/`_skip` calls |
| 3 | `agents/ruppert/trader/main.py` | Add import, pre-fetch daily consensus before band loop, add 4 poly fields to `opp` dict |

No changes to:
- `agents/ruppert/trader/crypto_15m.py` — covered by DS spec
- `config.py` — no new config knobs (shadow logging, not decision logic)
- `strategy.py` — no weight changes

---

## Part E: Why NOT to use `get_crypto_consensus()` alone for daily modules

| Factor | `get_crypto_consensus()` | `get_crypto_daily_consensus()` |
|--------|-------------------------|-------------------------------|
| Search keywords | "bitcoin up", "btc 15min" | "bitcoin daily", "btc above", "btc end of day" |
| Scoring bias | +10 for 15min/1hr terms | +10 for daily/eod/today terms; -5 for 15min/1hr |
| Cache TTL | 5 minutes | 10 minutes |
| Best for | 15m module (fast-settling) | Daily modules (8-24h settlement horizon) |
| Fallback | None | Falls back to `get_crypto_consensus()` if no daily market found |

The fallback ensures we always get *some* data for shadow logging even when Polymarket lacks daily-specific markets. The `horizon` field in the return dict tells the analyst which type of market was matched.

---

## Part F: Acceptance Checklist

- [ ] `polymarket_client.py`: `get_crypto_daily_consensus()` added, tested manually (returns dict or None)
- [ ] `crypto_1d.py`: `decisions_1d.jsonl` entries include all 7 poly fields (null when unavailable)
- [ ] `crypto_1d.py`: S5 data logged even on SKIP decisions (after signal computation)
- [ ] `crypto_1d.py`: Early SKIPs (before signal computation) have null poly fields — NOT missing fields
- [ ] `main.py`: Band module `opp` dict includes 4 `poly_daily_*` fields
- [ ] `main.py`: Polymarket fetch failure does not block any band trades
- [ ] No signal weights changed in any file
- [ ] No decision logic changed in any file
- [ ] All Polymarket calls wrapped in `try/except`
- [ ] `None` is logged (not field omitted) when data unavailable

---

## Part G: Analysis Plan (Post-Implementation)

After 7 days of shadow data (target: 200+ crypto_1d decisions + 100+ band trades):

1. **Correlation: `poly_daily_yes_price` vs settlement outcome** — Does Polymarket daily consensus predict above/below settlement better than our composite score alone?
2. **Divergence analysis** — When `poly_daily_yes_price` disagrees with `P_above`, who is right more often?
3. **Coverage report** — How often is `poly_daily_yes_price` non-null? If <30% coverage, the daily keyword set needs expansion.
4. **Horizon comparison** — Compare predictive value of `poly_yes_price` (short-window) vs `poly_daily_yes_price` (daily) for daily module outcomes. Hypothesis: daily consensus will be more predictive for daily settlement.

If correlation is meaningful, Strategist will spec a weight change proposal (separate spec, separate approval cycle).

---

**Strategist — 2026-04-01**
