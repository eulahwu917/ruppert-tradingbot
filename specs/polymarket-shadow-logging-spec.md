# Polymarket Shadow Logging — Implementation Spec
**Author:** DS  
**Date:** 2026-03-31  
**Status:** Implementation-ready  
**Scope:** Shadow logging only. Zero weight changes. Zero decision logic changes.

---

## Overview

Log Polymarket consensus price at every trade entry decision across all four active modules. Data is appended to existing JSONL logs as new nullable fields. Polymarket must never block a trade: all fetches are wrapped in `try/except`, fallback is `None` for all fields.

---

## Prerequisites — Import Block

All four modules must import from the shared client. For modules that live outside the `agents/` tree (`environments/live/`), add a `sys.path` shim **before** the import so the workspace root is on the path.

### Shim (add to `environments/live/` files only, near top of file before other imports)

```python
import sys as _sys
from pathlib import Path as _Path
_WS_ROOT = _Path(__file__).resolve().parents[2]   # .../workspace
if str(_WS_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_WS_ROOT))
```

`parents[2]` is correct for files at depth `environments/live/<file>.py` (2 levels up = workspace root).  
`crypto_15m.py` already has its own `sys.path` shim — no new shim needed.

### Import line (add to each module)

```python
from agents.ruppert.data_analyst.polymarket_client import (
    get_crypto_consensus,
    get_markets_by_keyword,
    get_geo_signals,
)
```

---

## Staleness Guard (crypto_15m only)

`get_crypto_consensus` caches results for 5 minutes (TTL = 300 s). Any returned value is at most 5 minutes old — always under the 10-minute threshold. The staleness guard therefore fires only when the cache is cold and a fresh fetch is >10 min old. Implement defensively:

```python
import time as _time

_poly_result   = None
_poly_fetched  = None
try:
    _poly_result  = get_crypto_consensus(asset)
    _poly_fetched = _time.time()
except Exception:
    pass

_STALE_THRESHOLD_SECS = 600  # 10 minutes

if _poly_result and _poly_fetched:
    age_secs = _time.time() - _poly_fetched
    if age_secs > _STALE_THRESHOLD_SECS:
        polymarket_yes_price  = None
        polymarket_fetched_at = None
    else:
        polymarket_yes_price  = _poly_result.get("yes_price")
        polymarket_fetched_at = datetime.fromtimestamp(_poly_fetched, tz=timezone.utc).isoformat()
else:
    polymarket_yes_price  = None
    polymarket_fetched_at = None
```

> Note: `_time.time()` is intentionally used (not `time.time()`) to avoid any name collision with the existing `time` module usage in `crypto_15m.py`. Dev may rename the alias to match local convention.

---

## Module 1 — crypto_15m.py

**File:** `agents/ruppert/trader/crypto_15m.py`

### 1a. Replace the existing placeholder function

Remove the entire `get_polymarket_yes_prob` stub (lines ~390–396):

```python
# REMOVE THIS:
def get_polymarket_yes_prob(asset: str) -> float | None:
    """
    Check if Polymarket has a corresponding 15-min crypto market.
    Returns YES probability or None if unavailable.
    """
    # Polymarket doesn't have 15-min direction markets yet — placeholder
    return None
```

Replace with the import from the shared client (already covers this functionality via `get_crypto_consensus`).

### 1b. Add import

After the existing `from agents.ruppert.env_config import ...` block, add:

```python
from agents.ruppert.data_analyst.polymarket_client import get_crypto_consensus
```

Note: `get_crypto_consensus` already exists in `polymarket_client.py`. The existing `_fetch_crypto_consensus` / `get_crypto_consensus` implementation searches for short-term direction markets for BTC/ETH/XRP/DOGE/SOL. This replaces the placeholder.

### 1c. Update `_log_decision` signature

Current signature:
```python
def _log_decision(
    market_id, window_open_ts, window_close_ts, elapsed_secs,
    signals, kalshi, decision, skip_reason, edge, entry_price, position_usd,
):
```

New signature — add two keyword-only args at the end:
```python
def _log_decision(
    market_id, window_open_ts, window_close_ts, elapsed_secs,
    signals, kalshi, decision, skip_reason, edge, entry_price, position_usd,
    polymarket_yes_price=None,
    polymarket_fetched_at=None,
):
```

### 1d. Add fields to the record dict inside `_log_decision`

Inside the function, in the `record = { ... }` dict, append:

```python
'polymarket_yes_price':  polymarket_yes_price,
'polymarket_fetched_at': polymarket_fetched_at,
```

Full updated dict (only the new fields shown):
```python
record = {
    'ts': ...,
    # ... existing fields unchanged ...
    'position_usd': ...,
    # NEW:
    'polymarket_yes_price':  polymarket_yes_price,
    'polymarket_fetched_at': polymarket_fetched_at,
}
```

### 1e. Fetch Polymarket data in `evaluate_crypto_15m_entry`

**Location:** Immediately after the four signal fetches and before composite score computation.

Current code (signals block):
```python
    tfi = fetch_taker_flow_imbalance(symbol)
    obi = fetch_orderbook_imbalance(symbol)
    macd = fetch_macd_signal(symbol)
    oi = fetch_oi_conviction(symbol)

    tfi_z = tfi['tfi_z']
    ...
```

Insert the staleness-guard block (from Prerequisites section) **after `oi = fetch_oi_conviction(symbol)`** and **before** `raw_score = W_TFI * tfi_z + ...`:

```python
    # ── Shadow: Polymarket consensus price (logging only, no weight change) ──
    import time as _time
    _poly_result  = None
    _poly_fetched = None
    try:
        _poly_result  = get_crypto_consensus(asset)
        _poly_fetched = _time.time()
    except Exception:
        pass

    _STALE_SECS = 600
    if _poly_result and _poly_fetched and (_time.time() - _poly_fetched) <= _STALE_SECS:
        polymarket_yes_price  = _poly_result.get("yes_price")
        polymarket_fetched_at = datetime.fromtimestamp(_poly_fetched, tz=timezone.utc).isoformat()
    else:
        polymarket_yes_price  = None
        polymarket_fetched_at = None
    # ── End Polymarket shadow ──
```

> `import time as _time` at function scope is fine (idempotent, Python caches the import). If Dev prefers a module-level alias, move the import to the top of the file.

### 1f. Update the existing Polymarket divergence nudge block

The existing block (lines ~490–498) calls `get_polymarket_yes_prob(asset)` which no longer exists. Replace it with the already-fetched value:

```python
    # Polymarket divergence nudge — use shadow price already fetched above
    poly_nudge = 0.0
    poly_yes = polymarket_yes_price   # <-- was: get_polymarket_yes_prob(asset)
    kalshi_yes = yes_ask / 100.0
    _poly_div_threshold = getattr(config, 'CRYPTO_15M_POLY_DIVERGENCE_THRESHOLD', 0.03)
    _poly_nudge_weight   = getattr(config, 'CRYPTO_15M_POLY_NUDGE_WEIGHT', 0.3)
    if poly_yes is not None:
        divergence = poly_yes - kalshi_yes
        if abs(divergence) > _poly_div_threshold:
            poly_nudge = _poly_nudge_weight * divergence
```

This change has **zero net behavioral effect** because `get_polymarket_yes_prob` currently returns `None` always. The nudge only activates when a market is found; nothing changes in practice. But now it will actually log data for future correlation analysis.

### 1g. Pass new fields to the final `_log_decision` call

There are two `_log_decision` calls that fire after signal gathering (ENTER path and INSUFFICIENT_EDGE path). Update both:

**INSUFFICIENT_EDGE skip:**
```python
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', 'INSUFFICIENT_EDGE',
                       max(edge_yes, edge_no), None, None,
                       polymarket_yes_price=polymarket_yes_price,
                       polymarket_fetched_at=polymarket_fetched_at)
```

**Final ENTER call (last `_log_decision` in the function):**
```python
    _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                   signals, kalshi_info,
                   'ENTER', None,
                   edge, entry_price, position_usd,
                   polymarket_yes_price=polymarket_yes_price,
                   polymarket_fetched_at=polymarket_fetched_at)
```

All other `_log_decision` calls (EARLY_WINDOW, LATE_WINDOW, SIZE_TOO_SMALL, ORDER_FAILED, cap checks, strategy gate) are early exits before signal gathering — they will use the default `None` kwargs. No changes needed for those calls.

### Fields added to `decisions_15m.jsonl`

| Field | Type | Notes |
|-------|------|-------|
| `polymarket_yes_price` | `float \| null` | 0–1 probability. `null` if no market found or API failure |
| `polymarket_fetched_at` | `str \| null` | ISO 8601 UTC. `null` when price is `null` |

---

## Module 2 — geopolitical_scanner.py

**File:** `environments/live/geopolitical_scanner.py`

### 2a. Add sys.path shim and import

At the top of the file, after existing imports but before any `from X import Y` that would need the path:

```python
import sys as _sys
from pathlib import Path as _Path
_WS_ROOT = _Path(__file__).resolve().parents[2]
if str(_WS_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_WS_ROOT))

from agents.ruppert.data_analyst.polymarket_client import get_geo_signals, get_markets_by_keyword
```

### 2b. Modify `run_geo_scan()`

**Location:** Inside the for-loop body `for m in markets[:15]`, after building the per-market `flagged` dict entry.

**Step 1:** Before the loop, fetch all geo signals once (bulk call, not per-market):

```python
    # Shadow: fetch Polymarket geo signals once for the whole scan
    _poly_geo_markets = []
    try:
        _poly_geo_markets = get_geo_signals()   # uses default geo keywords
    except Exception:
        pass
```

Insert this block immediately after `markets = get_geo_markets()` and before `if not markets:`.

**Step 2:** Inside the for-loop, after building `search_query` and before `flagged.append(...)`, add the Polymarket match:

```python
        # Shadow: find closest matching Polymarket geo market by keyword
        _poly_geo_yes_price  = None
        _poly_geo_market     = None
        _poly_geo_fetched_at = None
        try:
            from datetime import timezone as _tz
            import time as _time
            # Search inline for this specific market's topic
            _kw_results = get_markets_by_keyword(search_query, limit=5)
            if _kw_results:
                _best = max(_kw_results, key=lambda m: m.get("volume_24h", 0))
                _poly_geo_yes_price  = _best.get("yes_price")
                _poly_geo_market     = _best.get("question")
                _poly_geo_fetched_at = datetime.utcnow().replace(tzinfo=_tz.utc).isoformat()
            elif _poly_geo_markets:
                # Fallback: scan the pre-fetched bulk results for a keyword match
                title_lower = title.lower()
                _candidates = [
                    pg for pg in _poly_geo_markets
                    if any(w in title_lower for w in (pg.get("question") or "").lower().split()[:4])
                ]
                if _candidates:
                    _best = max(_candidates, key=lambda m: m.get("volume_24h", 0))
                    _poly_geo_yes_price  = _best.get("yes_price")
                    _poly_geo_market     = _best.get("question")
                    _poly_geo_fetched_at = datetime.utcnow().replace(tzinfo=_tz.utc).isoformat()
        except Exception:
            pass
```

**Step 3:** Update the `flagged.append({...})` call to include the new fields:

```python
        flagged.append({
            'ticker': m.get('ticker'),
            'title': title,
            'yes_price': yes_price,
            'market_prob': round(yes_price / 100, 2),
            'news_volume': count,
            'news_signal': 'HIGH' if count >= 5 else ('MEDIUM' if count >= 2 else 'LOW'),
            'recent_headlines': headlines,
            'requires_human_review': True,
            # NEW shadow fields:
            'polymarket_geo_yes_price': _poly_geo_yes_price,
            'polymarket_geo_market':    _poly_geo_market,
            'polymarket_fetched_at':    _poly_geo_fetched_at,
        })
```

No changes to the log-write block — it already writes the full `flagged` dict.

### Fields added to `logs/geopolitical_scout.jsonl`

| Field | Type | Notes |
|-------|------|-------|
| `polymarket_geo_yes_price` | `float \| null` | 0–1 |
| `polymarket_geo_market` | `str \| null` | Market question text |
| `polymarket_fetched_at` | `str \| null` | ISO 8601 UTC |

---

## Module 3 — fed_client.py

**File:** `environments/live/fed_client.py`

### Context note

`fed_client.py` already has deep Polymarket integration via `get_polymarket_fomc_probabilities()` (a bespoke slug-based FOMC fetch). This shadow logging adds a **second, simpler** Polymarket lookup using the shared `get_markets_by_keyword` client — providing a keyword-search-based consensus price alongside the existing slug-based probability. Both coexist.

### 3a. Add sys.path shim and import

Add near the top of file after existing imports:

```python
import sys as _sys
from pathlib import Path as _Path
_WS_ROOT = _Path(__file__).resolve().parents[2]
if str(_WS_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_WS_ROOT))

from agents.ruppert.data_analyst.polymarket_client import get_markets_by_keyword as _pm_get_markets
```

Using `_pm_get_markets` alias avoids any collision with local function names.

### 3b. Add helper function

Add near the bottom of the file, before `run_fed_scan()`:

```python
def _get_polymarket_fed_shadow() -> tuple:
    """
    Keyword-search fallback: find the highest-volume active Fed rate market.
    Returns (cut_probability, market_title, fetched_at_iso) — all None on failure.
    Shadow logging only. Never raises.
    """
    try:
        from datetime import timezone as _tz
        results = _pm_get_markets("Fed rate", limit=10)
        if not results:
            results = _pm_get_markets("FOMC rate decision", limit=10)
        if not results:
            return None, None, None
        best = max(results, key=lambda m: m.get("volume_24h", 0))
        fetched_at = datetime.now(timezone.utc).isoformat()
        return best.get("yes_price"), best.get("question"), fetched_at
    except Exception:
        return None, None, None
```

### 3c. Add shadow fields to `get_fed_signal()`

**Location:** Inside `get_fed_signal()`, immediately before `_save_scan_result(best_signal)` at the end of the function (just before the final `return best_signal`).

```python
    # Shadow: Polymarket keyword-search Fed price (supplement to slug-based poly_probs)
    _pm_cut_prob, _pm_fed_market, _pm_fed_fetched_at = _get_polymarket_fed_shadow()
    best_signal["polymarket_cut_probability"] = _pm_cut_prob
    best_signal["polymarket_fed_market"]      = _pm_fed_market
    best_signal["polymarket_fetched_at"]      = _pm_fed_fetched_at
```

Also add the same three fields to the `no_signal` / skip-path result dicts in `get_fed_signal()` that get passed to `_save_scan_result`. These appear in multiple early-return branches (e.g., `all_prob_sources_unavailable`, `kalshi_markets_unavailable`, etc.). For each dict:

```python
    _result = {
        "status": "no_signal",
        # ... existing fields ...
        # NEW:
        "polymarket_cut_probability": None,
        "polymarket_fed_market":      None,
        "polymarket_fetched_at":      None,
    }
```

> Dev note: there are ~5 early-return `_result` dicts in `get_fed_signal`. Add the three `None` fields to each. Do not call `_get_polymarket_fed_shadow()` in the early-return paths — just set `None` directly (avoids wasted API calls when outside the signal window).

Only call `_get_polymarket_fed_shadow()` on the **success path** (immediately before the final `return best_signal`).

### Fields added to `logs/fed_scan_latest.json`

| Field | Type | Notes |
|-------|------|-------|
| `polymarket_cut_probability` | `float \| null` | YES price of best-matching Fed market (keyword search) |
| `polymarket_fed_market` | `str \| null` | Market question text |
| `polymarket_fetched_at` | `str \| null` | ISO 8601 UTC |

---

## Module 4 — economics_scanner.py

**File:** `environments/live/economics_scanner.py`

### 4a. Add sys.path shim and import

After existing imports at top of file:

```python
import sys as _sys
from pathlib import Path as _Path
_WS_ROOT = _Path(__file__).resolve().parents[2]
if str(_WS_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_WS_ROOT))

from agents.ruppert.data_analyst.polymarket_client import get_markets_by_keyword as _pm_get_markets
```

### 4b. Series → keyword mapping

Add as a module-level constant near the `ACTIVE_ECON_SERIES` list:

```python
# Polymarket shadow logging: keyword per Kalshi econ series
_SERIES_POLY_KEYWORD: dict[str, str] = {
    'KXCPI':        'CPI',
    'KXFED':        'Fed rate',
    'KXECONSTATU3': 'unemployment',
    'KXUE':         'unemployment',
    'KXWRECSS':     'recession',
}
```

### 4c. Modify `analyze_market()`

**Location:** Inside `analyze_market()`, after the early-return checks (`if volume < MIN_VOLUME`, etc.) and before `return _build_opportunity(...)`.

```python
    # Shadow: Polymarket keyword-search price for this econ market
    _poly_econ_yes_price = None
    _poly_econ_market    = None
    _poly_fetched_at     = None
    try:
        from datetime import timezone as _tz
        _kw = _SERIES_POLY_KEYWORD.get(series, '')
        if _kw:
            _poly_results = _pm_get_markets(_kw, limit=10)
            if _poly_results:
                _best = max(_poly_results, key=lambda m: m.get("volume_24h", 0))
                _poly_econ_yes_price = _best.get("yes_price")
                _poly_econ_market    = _best.get("question")
                _poly_fetched_at     = datetime.now().astimezone(_tz.utc).isoformat()
    except Exception:
        pass
```

Then pass the three values to `_build_opportunity`:

```python
    return _build_opportunity(
        market, signal, market_prob,
        poly_econ_yes_price=_poly_econ_yes_price,
        poly_econ_market=_poly_econ_market,
        poly_fetched_at=_poly_fetched_at,
    )
```

### 4d. Modify `_build_opportunity()`

**Signature change:**
```python
def _build_opportunity(
    market: dict,
    signal: dict,
    market_prob: float,
    poly_econ_yes_price=None,
    poly_econ_market=None,
    poly_fetched_at=None,
) -> dict:
```

**Add to returned dict:**
```python
    return {
        'ticker': ...,
        # ... all existing fields unchanged ...
        'flagged_at': datetime.now().isoformat(),
        # NEW:
        'polymarket_econ_yes_price': poly_econ_yes_price,
        'polymarket_econ_market':    poly_econ_market,
        'polymarket_fetched_at':     poly_fetched_at,
    }
```

### Fields added to economics opportunity dicts

| Field | Type | Notes |
|-------|------|-------|
| `polymarket_econ_yes_price` | `float \| null` | Best-matching market YES price |
| `polymarket_econ_market` | `str \| null` | Market question |
| `polymarket_fetched_at` | `str \| null` | ISO 8601 UTC |

---

## Summary of File Changes

| Module | File Path | Changes |
|--------|-----------|---------|
| crypto_15m | `agents/ruppert/trader/crypto_15m.py` | Remove placeholder fn, add import, extend `_log_decision` signature, add fetch block after signals, update 2 log calls |
| geo | `environments/live/geopolitical_scanner.py` | Add sys.path shim, import, bulk pre-fetch before loop, per-market match inside loop, 3 fields in flagged dict |
| fed | `environments/live/fed_client.py` | Add sys.path shim, import, helper fn `_get_polymarket_fed_shadow`, 3 fields in signal dict (None in early-exit paths, live fetch only on success path) |
| econ | `environments/live/economics_scanner.py` | Add sys.path shim, import, keyword map constant, fetch in `analyze_market`, 3 kwargs through `_build_opportunity` |

---

## Acceptance Checklist

- [ ] All 4 modules log Polymarket fields on every entry/evaluation
- [ ] None of the 4 modules change any signal weights or decision logic
- [ ] API failure in any module → `null` fields, trade proceeds normally
- [ ] `decisions_15m.jsonl` entries include `polymarket_yes_price` and `polymarket_fetched_at`
- [ ] `get_polymarket_yes_prob` stub removed; replaced with `get_crypto_consensus` from shared client
- [ ] All four modules import from `agents.ruppert.data_analyst.polymarket_client`  
- [ ] Staleness guard in crypto_15m: `null` if age > 600s  
- [ ] No `try/except` missing — every Polymarket call is wrapped  
- [ ] `None` is logged (not field omitted) when unavailable  

---

**DS**
