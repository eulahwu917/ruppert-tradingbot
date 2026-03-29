# STRATEGIST SPEC — Crypto 15m Threshold Relaxation
**Date:** 2026-03-29  
**Author:** Strategist  
**Status:** Approved by David — ready for Dev  
**Purpose:** Relax DEMO thresholds to increase trade frequency for data collection. Tag every trade so Optimizer and Data Scientist can segment "clean" vs relaxed-threshold data.

---

## Overview

Four changes, two files, one pipeline requirement:

1. **`environments/demo/config.py`** — change two existing constants, add two new ones
2. **`agents/ruppert/trader/crypto_15m.py`** — wire config into R2/R4, refactor `check_risk_filters` return type, compute data quality tags, add tags to `opp` dict
3. **`agents/ruppert/data_scientist/logger.py`** — add new tag fields to `build_trade_entry` so they survive to the JSONL log
4. **No changes to live/prod config** — these relaxations are DEMO only

---

## Config Changes

**File:** `environments/demo/config.py`

### 1a. Change existing constants

```python
# BEFORE:
CRYPTO_15M_MIN_EDGE          = 0.08   # 8% minimum edge to enter
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.003  # book depth must be >= 0.3% of open interest

# AFTER:
CRYPTO_15M_MIN_EDGE          = 0.05   # DEMO relaxed: 5% minimum edge (was 0.08)
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.001  # DEMO relaxed: book depth >= 0.1% of OI (was 0.003)
```

### 1b. Add two new constants (after the existing CRYPTO_15M block)

Insert immediately after `CRYPTO_15M_DAILY_CAP_PCT`:

```python
CRYPTO_15M_MAX_SPREAD        = 15    # DEMO relaxed: max spread cents (was hardcoded 8 in crypto_15m.py)
CRYPTO_15M_THIN_MARKET_RATIO = 0.05  # DEMO relaxed: min OKX vol ratio vs 30d avg (was hardcoded 0.25)
```

**Full CRYPTO_15M block after changes:**
```python
# ── 15-Min Crypto Direction (KXBTC15M / KXETH15M / KXXRP15M / KXDOGE15M) ────
CRYPTO_15M_MIN_EDGE          = 0.05   # DEMO relaxed: 5% minimum edge (was 0.08)
CRYPTO_15M_LIQUIDITY_MIN_PCT = 0.001  # DEMO relaxed: book depth >= 0.1% of OI (was 0.003)
CRYPTO_15M_SIGMOID_SCALE     = 1.0    # sigmoid scale factor (autoresearcher-tunable)
CRYPTO_15M_DAILY_CAP_PCT     = 0.04   # 4% of capital per day
CRYPTO_15M_MAX_SPREAD        = 15     # DEMO relaxed: max spread cents (was hardcoded 8 in crypto_15m.py)
CRYPTO_15M_THIN_MARKET_RATIO = 0.05   # DEMO relaxed: min OKX vol ratio vs 30d avg (was hardcoded 0.25)
```

---

## Code Changes

### File: `agents/ruppert/trader/crypto_15m.py`

---

#### Change 2a: Refactor `check_risk_filters` return type — `str | None` → `dict`

**Reason:** The function currently fetches `okx_vol / avg_okx_vol` internally but discards the ratio. We need to return it so the caller can compute `okx_volume_pct` for data quality tagging without a second API call.

**Caller impact:** The call site in `evaluate_crypto_15m_entry` currently does:
```python
block_reason = check_risk_filters(...)
if block_reason:
```
This must change to use `block_result['block']` (see Change 2d below).

**BEFORE — function signature and return statements:**

```python
def check_risk_filters(
    symbol: str,
    asset: str,
    raw_score: float,
    yes_ask: int,
    yes_bid: int,
    book_depth_usd: float,
    tfi_stale: bool,
    obi_stale: bool,
    fr_z: float | None,
    dollar_oi: float = 0.0,
) -> str | None:
    """
    Apply all 10 risk filters. Returns block reason string or None if clear.
    """
    # R1: Extreme realized vol
    vol_5m, _ = _get_realized_5m_vol(symbol)
    avg_vol_30d = _fetch_30d_avg_okx_vol(symbol)
    if vol_5m is not None and avg_vol_30d is not None and avg_vol_30d > 0:
        if vol_5m > 3.0 * avg_vol_30d:
            return 'EXTREME_VOL'

    # R2: Wide spread
    spread = yes_ask - yes_bid
    if spread > 8:
        return 'WIDE_SPREAD'

    # R3: Thin Kalshi book — percentage of OI (scales with market activity)
    # Require book depth >= LIQUIDITY_MIN_PCT of open interest (default 0.3%)
    # Falls back to absolute $100 floor if OI is unavailable
    liquidity_min_pct = getattr(config, 'CRYPTO_15M_LIQUIDITY_MIN_PCT', 0.003)
    if dollar_oi > 0:
        min_depth = max(dollar_oi * liquidity_min_pct, 50.0)  # at least $50 floor
    else:
        min_depth = 100.0  # fallback if OI unavailable
    if book_depth_usd < min_depth:
        return 'LOW_KALSHI_LIQUIDITY'

    # R4: Thin underlying volume
    okx_vol = _fetch_okx_5m_volume(symbol)
    avg_okx_vol = _fetch_30d_avg_okx_vol(symbol)
    if okx_vol is not None and avg_okx_vol is not None and avg_okx_vol > 0:
        if okx_vol < 0.25 * avg_okx_vol:
            return 'THIN_MARKET'

    # R5: Stale data
    if tfi_stale:
        return 'TFI_STALE'
    if obi_stale:
        return 'OBI_STALE'

    # R6: Extreme funding
    if fr_z is not None and abs(fr_z) > 3.0:
        return 'EXTREME_FUNDING'

    # R7: Low conviction
    if abs(raw_score) < 0.15:
        return 'LOW_CONVICTION'

    # R8: Session drawdown
    session_pnl = _get_session_pnl_15m()
    from agents.ruppert.data_scientist.capital import get_capital
    capital = get_capital()
    daily_alloc = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
    if session_pnl < -0.05 * daily_alloc:
        return 'DRAWDOWN_PAUSE'

    # R9: Macro event (reuse from main cycle if available)
    try:
        from ruppert_cycle import has_macro_event_within
        if has_macro_event_within(minutes=30):
            return 'MACRO_EVENT_RISK'
    except (ImportError, AttributeError):
        pass  # Not available in all contexts

    # R10: Coinbase-OKX basis
    coinbase_price = fetch_coinbase_price(asset)
    okx_price = fetch_okx_price(symbol)
    if coinbase_price and okx_price and okx_price > 0:
        basis = abs(coinbase_price - okx_price) / okx_price
        if basis > 0.0015:
            return 'BASIS_RISK'

    return None
```

**AFTER — full replacement:**

```python
def check_risk_filters(
    symbol: str,
    asset: str,
    raw_score: float,
    yes_ask: int,
    yes_bid: int,
    book_depth_usd: float,
    tfi_stale: bool,
    obi_stale: bool,
    fr_z: float | None,
    dollar_oi: float = 0.0,
) -> dict:
    """
    Apply all 10 risk filters.

    Returns dict:
        {
            'block': str | None,       # block reason, or None if all filters pass
            'okx_volume_pct': float | None,  # actual okx_vol / avg_30d (e.g. 0.12 = 12%)
        }
    'block' is None means clear to enter.
    'okx_volume_pct' is always returned when available (even on block) for logging.
    """
    # R1: Extreme realized vol
    vol_5m, _ = _get_realized_5m_vol(symbol)
    avg_vol_30d = _fetch_30d_avg_okx_vol(symbol)
    if vol_5m is not None and avg_vol_30d is not None and avg_vol_30d > 0:
        if vol_5m > 3.0 * avg_vol_30d:
            return {'block': 'EXTREME_VOL', 'okx_volume_pct': None}

    # R2: Wide spread — now config-driven (DEMO: 15c, PROD default: 8c)
    spread = yes_ask - yes_bid
    max_spread = getattr(config, 'CRYPTO_15M_MAX_SPREAD', 8)
    if spread > max_spread:
        return {'block': 'WIDE_SPREAD', 'okx_volume_pct': None}

    # R3: Thin Kalshi book — percentage of OI (scales with market activity)
    # Require book depth >= LIQUIDITY_MIN_PCT of open interest
    # Falls back to absolute $100 floor if OI is unavailable
    liquidity_min_pct = getattr(config, 'CRYPTO_15M_LIQUIDITY_MIN_PCT', 0.003)
    if dollar_oi > 0:
        min_depth = max(dollar_oi * liquidity_min_pct, 50.0)  # at least $50 floor
    else:
        min_depth = 100.0  # fallback if OI unavailable
    if book_depth_usd < min_depth:
        return {'block': 'LOW_KALSHI_LIQUIDITY', 'okx_volume_pct': None}

    # R4: Thin underlying volume — now config-driven (DEMO: 0.05x, PROD default: 0.25x)
    okx_vol = _fetch_okx_5m_volume(symbol)
    avg_okx_vol = _fetch_30d_avg_okx_vol(symbol)
    okx_volume_pct: float | None = None
    if okx_vol is not None and avg_okx_vol is not None and avg_okx_vol > 0:
        okx_volume_pct = round(okx_vol / avg_okx_vol, 4)
        thin_market_ratio = getattr(config, 'CRYPTO_15M_THIN_MARKET_RATIO', 0.25)
        if okx_volume_pct < thin_market_ratio:
            return {'block': 'THIN_MARKET', 'okx_volume_pct': okx_volume_pct}

    # R5: Stale data
    if tfi_stale:
        return {'block': 'TFI_STALE', 'okx_volume_pct': okx_volume_pct}
    if obi_stale:
        return {'block': 'OBI_STALE', 'okx_volume_pct': okx_volume_pct}

    # R6: Extreme funding
    if fr_z is not None and abs(fr_z) > 3.0:
        return {'block': 'EXTREME_FUNDING', 'okx_volume_pct': okx_volume_pct}

    # R7: Low conviction
    if abs(raw_score) < 0.15:
        return {'block': 'LOW_CONVICTION', 'okx_volume_pct': okx_volume_pct}

    # R8: Session drawdown
    session_pnl = _get_session_pnl_15m()
    from agents.ruppert.data_scientist.capital import get_capital
    capital = get_capital()
    daily_alloc = capital * getattr(config, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04)
    if session_pnl < -0.05 * daily_alloc:
        return {'block': 'DRAWDOWN_PAUSE', 'okx_volume_pct': okx_volume_pct}

    # R9: Macro event (reuse from main cycle if available)
    try:
        from ruppert_cycle import has_macro_event_within
        if has_macro_event_within(minutes=30):
            return {'block': 'MACRO_EVENT_RISK', 'okx_volume_pct': okx_volume_pct}
    except (ImportError, AttributeError):
        pass  # Not available in all contexts

    # R10: Coinbase-OKX basis
    coinbase_price = fetch_coinbase_price(asset)
    okx_price = fetch_okx_price(symbol)
    if coinbase_price and okx_price and okx_price > 0:
        basis = abs(coinbase_price - okx_price) / okx_price
        if basis > 0.0015:
            return {'block': 'BASIS_RISK', 'okx_volume_pct': okx_volume_pct}

    return {'block': None, 'okx_volume_pct': okx_volume_pct}
```

---

#### Change 2b: Update call site in `evaluate_crypto_15m_entry`

**BEFORE** (the block after "── Risk Filters ──"):

```python
    # ── Risk Filters ──
    block_reason = check_risk_filters(
        symbol=symbol,
        asset=asset,
        raw_score=raw_score,
        yes_ask=yes_ask,
        yes_bid=yes_bid,
        book_depth_usd=book_depth_usd,
        tfi_stale=tfi['stale'],
        obi_stale=obi['stale'],
        fr_z=fr_z,
        dollar_oi=dollar_oi,
    )
    if block_reason:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', block_reason, None, None, None)
        return
```

**AFTER:**

```python
    # ── Risk Filters ──
    risk_result = check_risk_filters(
        symbol=symbol,
        asset=asset,
        raw_score=raw_score,
        yes_ask=yes_ask,
        yes_bid=yes_bid,
        book_depth_usd=book_depth_usd,
        tfi_stale=tfi['stale'],
        obi_stale=obi['stale'],
        fr_z=fr_z,
        dollar_oi=dollar_oi,
    )
    block_reason = risk_result['block']
    okx_volume_pct = risk_result['okx_volume_pct']  # used for data quality tagging

    if block_reason:
        _log_decision(ticker, window_open_ts, window_close_ts, elapsed_secs,
                       signals, kalshi_info, 'SKIP', block_reason, None, None, None)
        return
```

---

#### Change 2c: Add data quality tagging block

**Location:** Insert immediately after the `if block_reason: ... return` block above, before the "── Entry Logic ──" comment.

**Insert this new block:**

```python
    # ── Data Quality Tagging ──
    # Compare actual values against original PROD thresholds to classify trade quality.
    # These constants define "clean" data regardless of what config is currently set to.
    # Priority when multiple thresholds are relaxed: thin_market > wide_spread > low_liquidity
    _STRICT_MAX_SPREAD        = 8      # original R2 production threshold
    _STRICT_THIN_MARKET_RATIO = 0.25   # original R4 production threshold
    _STRICT_LIQUIDITY_MIN_PCT = 0.003  # original R3 production threshold

    spread = yes_ask - yes_bid

    spread_clean = spread <= _STRICT_MAX_SPREAD

    thin_mkt_clean = (
        okx_volume_pct is None  # couldn't fetch — treat as unknown, don't penalize
        or okx_volume_pct >= _STRICT_THIN_MARKET_RATIO
    )

    strict_min_depth = (
        max(dollar_oi * _STRICT_LIQUIDITY_MIN_PCT, 50.0) if dollar_oi > 0 else 100.0
    )
    liquidity_clean = book_depth_usd >= strict_min_depth

    if not thin_mkt_clean:
        data_quality = 'thin_market'
    elif not spread_clean:
        data_quality = 'wide_spread'
    elif not liquidity_clean:
        data_quality = 'low_liquidity'
    else:
        data_quality = 'standard'
```

---

#### Change 2d: Add tags to the `opp` dict

**BEFORE** (the `opp = { ... }` dict construction near end of `evaluate_crypto_15m_entry`):

```python
    opp = {
        'ticker': ticker,
        'title': f'{asset} 15m direction',
        'side': direction,
        'edge': round(edge, 4),
        'win_prob': round(P_win, 4),
        'confidence': round(abs(raw_score), 3),
        'market_prob': yes_ask / 100.0 if direction == 'yes' else (100 - yes_bid) / 100.0,
        'model_prob': round(P_final, 4),
        'source': 'crypto_15m',
        'module': 'crypto_15m',
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'hours_to_settlement': max(0, (900 - elapsed_secs) / 3600),
        'action': 'buy',
        'contracts': contracts,
        'size_dollars': round(position_usd, 2),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': str(date.today()),
        'scan_price': entry_price,
    }
```

**AFTER** — append the four new tag fields:

```python
    opp = {
        'ticker': ticker,
        'title': f'{asset} 15m direction',
        'side': direction,
        'edge': round(edge, 4),
        'win_prob': round(P_win, 4),
        'confidence': round(abs(raw_score), 3),
        'market_prob': yes_ask / 100.0 if direction == 'yes' else (100 - yes_bid) / 100.0,
        'model_prob': round(P_final, 4),
        'source': 'crypto_15m',
        'module': 'crypto_15m',
        'yes_ask': yes_ask,
        'yes_bid': yes_bid,
        'hours_to_settlement': max(0, (900 - elapsed_secs) / 3600),
        'action': 'buy',
        'contracts': contracts,
        'size_dollars': round(position_usd, 2),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date': str(date.today()),
        'scan_price': entry_price,
        # ── Data quality tags (for Optimizer / Data Scientist segmentation) ──
        'data_quality':          data_quality,
        'okx_volume_pct':        okx_volume_pct,                  # float ratio, e.g. 0.12 = 12% of 30d avg
        'kalshi_book_depth_usd': round(book_depth_usd, 2),        # USD depth at entry
        'kalshi_spread_cents':   yes_ask - yes_bid,               # spread in cents at entry
    }
```

---

### File: `agents/ruppert/data_scientist/logger.py`

#### Change 3: Add new tag fields to `build_trade_entry`

`build_trade_entry` hardcodes the fields it copies from `opportunity`. The four new tag fields must be explicitly added or they will be silently dropped before reaching the JSONL log.

**BEFORE** (end of the `return { ... }` dict in `build_trade_entry`):

```python
    return {
        'trade_id':     str(uuid.uuid4()),
        'timestamp':    opportunity.get('timestamp') or datetime.now().isoformat(),
        'date':         opportunity.get('date') or date.today().isoformat(),
        'ticker':       opportunity['ticker'],
        'title':        opportunity.get('title', opportunity['ticker']),
        'side':         opportunity['side'],
        'action':       action,
        'action_detail': raw_action,
        'source':       source,
        'module':       module,
        'noaa_prob':    opportunity.get('noaa_prob'),
        'market_prob':  opportunity.get('market_prob'),
        'edge':         opportunity.get('edge'),
        'confidence':   opportunity.get('confidence') if opportunity.get('confidence') is not None
                        else abs(opportunity.get('edge') or 0),
        'size_dollars': size,
        'contracts':    contracts,
        'scan_contracts': opportunity.get('scan_contracts'),
        'fill_contracts': opportunity.get('fill_contracts'),
        'scan_price':   opportunity.get('scan_price'),
        'fill_price':   opportunity.get('fill_price'),
        'order_result': order_result,
    }
```

**AFTER** — append four new fields at end of the dict:

```python
    return {
        'trade_id':     str(uuid.uuid4()),
        'timestamp':    opportunity.get('timestamp') or datetime.now().isoformat(),
        'date':         opportunity.get('date') or date.today().isoformat(),
        'ticker':       opportunity['ticker'],
        'title':        opportunity.get('title', opportunity['ticker']),
        'side':         opportunity['side'],
        'action':       action,
        'action_detail': raw_action,
        'source':       source,
        'module':       module,
        'noaa_prob':    opportunity.get('noaa_prob'),
        'market_prob':  opportunity.get('market_prob'),
        'edge':         opportunity.get('edge'),
        'confidence':   opportunity.get('confidence') if opportunity.get('confidence') is not None
                        else abs(opportunity.get('edge') or 0),
        'size_dollars': size,
        'contracts':    contracts,
        'scan_contracts': opportunity.get('scan_contracts'),
        'fill_contracts': opportunity.get('fill_contracts'),
        'scan_price':   opportunity.get('scan_price'),
        'fill_price':   opportunity.get('fill_price'),
        'order_result': order_result,
        # ── Data quality tags (crypto_15m only; None for all other modules) ──
        'data_quality':          opportunity.get('data_quality'),
        'okx_volume_pct':        opportunity.get('okx_volume_pct'),
        'kalshi_book_depth_usd': opportunity.get('kalshi_book_depth_usd'),
        'kalshi_spread_cents':   opportunity.get('kalshi_spread_cents'),
    }
```

---

## Data Quality Tagging

### Tag: `data_quality`

| Value | Meaning | When set |
|---|---|---|
| `'standard'` | All original PROD thresholds passed | spread ≤ 8c AND OKX vol ≥ 25% of 30d avg AND Kalshi book ≥ 0.3% of OI |
| `'thin_market'` | Would have been blocked by original R4 | OKX vol < 25% of 30d avg (but ≥ 5% — current DEMO threshold) |
| `'wide_spread'` | Would have been blocked by original R2 | spread > 8c (but ≤ 15c — current DEMO threshold) |
| `'low_liquidity'` | Would have been blocked by original R3 | Kalshi book depth < 0.3% of OI (but ≥ 0.1% — current DEMO threshold) |

**Priority when multiple thresholds are relaxed:** `thin_market` > `wide_spread` > `low_liquidity`. The single highest-priority degradation wins. This is a deliberate simplification — edge cases with two simultaneous degradations are rare and the dominant factor matters more for Optimizer segmentation.

**When `okx_volume_pct` is `None`:** OKX volume data was unavailable. `thin_mkt_clean` defaults to `True` (benefit of the doubt). Tag will still reflect spread and liquidity status.

### Tag: `okx_volume_pct`

- Float, ratio of current 5-min OKX volume to 30-day average 5-min volume
- `None` if OKX volume fetch failed
- Examples: `0.08` = 8% of normal volume (thin), `1.20` = 120% of normal (thick)

### Tag: `kalshi_book_depth_usd`

- Float, USD value of book depth passed into `evaluate_crypto_15m_entry`
- Sourced from the WS feed / REST tick; represents depth at moment of entry decision

### Tag: `kalshi_spread_cents`

- Integer, `yes_ask - yes_bid` at entry decision time
- Units: cents (same as yes_ask/yes_bid)

### Where Tags End Up

Flow: `opp` dict → `log_trade(opp, ...)` → `build_trade_entry(opp, ...)` → JSONL record in `logs/trades/trades_YYYY-MM-DD.jsonl`

After this change, each crypto_15m trade record will contain:
```json
{
  "trade_id": "...",
  "ticker": "KXBTC15M-...",
  "module": "crypto_15m",
  "data_quality": "thin_market",
  "okx_volume_pct": 0.08,
  "kalshi_book_depth_usd": 1450.00,
  "kalshi_spread_cents": 6,
  ...
}
```

Non-crypto_15m trades will have `null` for all four fields (no breaking change to other modules).

---

## QA Test Criteria

### QA-1: Config constants exist and have correct values

```python
import config
assert config.CRYPTO_15M_MIN_EDGE == 0.05
assert config.CRYPTO_15M_LIQUIDITY_MIN_PCT == 0.001
assert config.CRYPTO_15M_MAX_SPREAD == 15
assert config.CRYPTO_15M_THIN_MARKET_RATIO == 0.05
```

### QA-2: `check_risk_filters` returns dict with correct keys

```python
# Call with known-passing values; assert return type and shape
result = check_risk_filters(symbol='BTC-USDT-SWAP', ...)
assert isinstance(result, dict)
assert 'block' in result
assert 'okx_volume_pct' in result
# Block path: assert result['block'] == 'WIDE_SPREAD' when spread > 15
# Clear path: assert result['block'] is None
```

### QA-3: R2 spread threshold uses config value (not hardcoded 8)

Inject `CRYPTO_15M_MAX_SPREAD = 15` in config mock. Call `check_risk_filters` with `yes_ask=20, yes_bid=10` (spread=10, was blocked at 8, passes at 15). Assert `result['block'] is None`.

Confirm original behavior preserved: spread=16 → `result['block'] == 'WIDE_SPREAD'`.

### QA-4: R4 OKX volume threshold uses config value (not hardcoded 0.25)

Mock `_fetch_okx_5m_volume` to return `0.10 * avg` and `CRYPTO_15M_THIN_MARKET_RATIO = 0.05`. Assert `result['block'] is None` and `result['okx_volume_pct'] == 0.10`.

Confirm original behavior: volume at `0.03 * avg` → `result['block'] == 'THIN_MARKET'`.

### QA-5: `data_quality` tag is correct for each scenario

| Scenario | Expected `data_quality` |
|---|---|
| spread=6, okx_vol_pct=0.40, depth=2000 | `'standard'` |
| spread=6, okx_vol_pct=0.10, depth=2000 | `'thin_market'` |
| spread=12, okx_vol_pct=0.40, depth=2000 | `'wide_spread'` |
| spread=6, okx_vol_pct=0.40, depth below strict min | `'low_liquidity'` |
| spread=12, okx_vol_pct=0.10, depth=2000 | `'thin_market'` (priority) |

QA: Write unit test with mocked config thresholds, call the tagging block directly, assert each case.

### QA-6: Tags survive to JSONL trade log

Run in DRY_RUN mode. Trigger one trade entry via `evaluate_crypto_15m_entry` with known values. Read back the JSONL log. Assert the trade record contains:
- `'data_quality'` key with value in `{'standard', 'thin_market', 'wide_spread', 'low_liquidity'}`
- `'okx_volume_pct'` key (float or None)
- `'kalshi_book_depth_usd'` key (float)
- `'kalshi_spread_cents'` key (int)

### QA-7: Non-crypto_15m trades are unaffected

Run a weather trade through `log_trade`. Assert the logged record has `data_quality: null` (not missing, not erroring). Other fields (`size_dollars`, `edge`, etc.) must be unchanged.

### QA-8: Old call sites — confirm no bare string comparison on risk filter result

`grep` for any code that does `if block_reason == 'THIN_MARKET'` or `block_reason in (...)` patterns outside of crypto_15m.py. If any exist, update them to `result['block'] == 'THIN_MARKET'`. (Expected: none outside this file, but confirm.)

---

## Notes for Dev

1. **No live config changes.** This spec only touches `environments/demo/config.py`. Prod uses `environments/live/config.py` which has no `CRYPTO_15M_MAX_SPREAD` or `CRYPTO_15M_THIN_MARKET_RATIO` — the `getattr(..., default)` fallbacks in the code will keep prod behavior unchanged.

2. **`_STRICT_*` constants are local to `evaluate_crypto_15m_entry`.** They're defined inline in the tagging block, not in config. This is intentional — they define what "clean" means and should not be accidentally overridden per-environment.

3. **`okx_volume_pct` is computed in `check_risk_filters`, not re-fetched.** The refactored return dict carries it directly to the tagging block. No extra API calls.

4. **`build_trade_entry` change is additive only** — no existing fields removed or modified. All other modules get `null` for the four new fields, which is correct.
