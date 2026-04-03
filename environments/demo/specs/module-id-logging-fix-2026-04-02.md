# Module ID Logging Bug — WS Entry Path Hardcodes `module='crypto'`

**Date:** 2026-04-02
**Author:** DS (Ruppert)
**Priority:** P1 — 26 records with wrong module ID (19 on Apr 2, 7 on Apr 1)
**Status:** Spec complete — hand to Dev
**Related:** settlement-ws-hourly-fix-2026-04-02.md (Fix 2 is the same code change)

---

## Problem

26 trade records (19 on 2026-04-02, 7 on 2026-04-01) logged `module='crypto'` instead
of specific per-asset IDs like `crypto_band_daily_btc` or `crypto_threshold_daily_btc`.

**Expected:** `crypto_band_daily_btc`, `crypto_band_daily_eth`, `crypto_threshold_daily_btc`, etc.
**Actual:** `crypto`

This breaks:
- Dashboard module-level P&L bucketing (all band/threshold daily lumped into generic "crypto")
- Per-module cap enforcement (`get_daily_exposure('crypto_band_daily_btc')` returns 0)
- Position tracker time-decay stop-loss (requires `module.startswith('crypto_band_daily_')`)

---

## Root Cause

**File:** `agents/ruppert/data_analyst/ws_feed.py`

The `evaluate_crypto_entry()` function (line 286) is the WS real-time entry path for
band and threshold daily positions.  It hardcodes the module in two places:

### Place 1: Opportunity dict (line 414)
```python
opp = {
    ...
    'module': 'crypto',     # ← HARDCODED, should be per-asset
    ...
}
```

This flows into `log_trade(opp, ...)` at line 479.  Since `opp['module']` is non-empty,
`build_trade_entry()` (logger.py:106) uses it directly — the `classify_module()` fallback
never fires.

### Place 2: Position tracker registration (line 498–499)
```python
position_tracker.add_position(ticker, fill_contracts, side, fill_price,
                              module='crypto', title=opp.get('title', ''))
```

This means the position_tracker stores `module='crypto'`, disabling the time-decay
stop-loss check at position_tracker.py:401.

### Why the scanner path is correct

The scheduled scanner path (`crypto_band_daily.py` → `trader.py`) correctly sets
per-asset module IDs:

- `crypto_band_daily.py:183–190` defines `_SERIES_TO_BAND_MODULE` mapping
- `crypto_band_daily.py:323` sets `opp['module'] = _t_module`
- `crypto_threshold_daily.py:54–58` defines `ASSET_MODULE_NAMES_1D`
- `crypto_threshold_daily.py:1049` sets `'module': _asset_module`
- `trader.py:97,136` passes `module=opportunity.get('module', '')` to position_tracker

**Only the WS entry path is broken.**

---

## Fix

**Same as Fix 2 in settlement-ws-hourly-fix-2026-04-02.md.**

In `ws_feed.py evaluate_crypto_entry()`, derive module from `asset` (already parsed at
lines 305–318) and `strike_type` (parsed at lines 328–344):

```python
# After line 344, before line 346
_WS_MODULE_MAP = {
    ('BTC', 'between'): 'crypto_band_daily_btc',
    ('ETH', 'between'): 'crypto_band_daily_eth',
    ('XRP', 'between'): 'crypto_band_daily_xrp',
    ('DOGE', 'between'): 'crypto_band_daily_doge',
    ('SOL', 'between'): 'crypto_band_daily_sol',
    ('BTC', 'greater'): 'crypto_threshold_daily_btc',
    ('BTC', 'less'):    'crypto_threshold_daily_btc',
    ('ETH', 'greater'): 'crypto_threshold_daily_eth',
    ('ETH', 'less'):    'crypto_threshold_daily_eth',
    ('SOL', 'greater'): 'crypto_threshold_daily_sol',
    ('SOL', 'less'):    'crypto_threshold_daily_sol',
}
_ws_module = _WS_MODULE_MAP.get((asset, strike_type), f'crypto_band_daily_{asset.lower()}')
```

Then update:
- **Line 414:** `'module': _ws_module,`
- **Line 498–499:** `module=opp.get('module', 'crypto'),`
- **Line 430:** `_module_deployed = get_daily_exposure(_ws_module)`
- **Line 432:** `module=_ws_module` in `should_enter()` call

---

## Log Migration (26 records)

The 26 existing records in `logs/trades/trades_2026-04-01.jsonl` and
`trades_2026-04-02.jsonl` need their `module` field corrected.

### Migration logic

For each record where `module == 'crypto'` and ticker matches band/threshold patterns:

| Ticker pattern | Correct module |
|---------------|---------------|
| `KXBTC-*-B*` | `crypto_band_daily_btc` |
| `KXETH-*-B*` | `crypto_band_daily_eth` |
| `KXXRP-*-B*` | `crypto_band_daily_xrp` |
| `KXDOGE-*-B*` | `crypto_band_daily_doge` |
| `KXSOL-*-B*` | `crypto_band_daily_sol` |
| `KXBTCD-*-T*` | `crypto_threshold_daily_btc` |
| `KXETHD-*-T*` | `crypto_threshold_daily_eth` |
| `KXSOLD-*-T*` | `crypto_threshold_daily_sol` |

### Script location

Write migration to `scripts/pnl_correction_module_id.py`.  Pattern:

```python
# For each trades JSONL file in [trades_2026-04-01.jsonl, trades_2026-04-02.jsonl]:
#   Read all lines
#   For lines where module == 'crypto':
#     Derive correct module from ticker using pattern table above
#     Replace module field
#   Write back atomically (write to tmp, rename)
```

**Dry-run mode first** — print proposed changes, require `--apply` flag to write.

---

## Files Changed

| File | Change |
|------|--------|
| `agents/ruppert/data_analyst/ws_feed.py:345–414,430,432,498` | Derive per-asset module ID |
| `scripts/pnl_correction_module_id.py` (NEW) | Migration script for 26 log records |

---

## Testing

1. Dry-run WS entry for `KXBTCD-*-T*` ticker → verify log shows `crypto_threshold_daily_btc`
2. Dry-run WS entry for `KXETH-*-B*` ticker → verify log shows `crypto_band_daily_eth`
3. Run migration script in dry-run → verify 26 records identified with correct new modules
4. After migration, verify dashboard module bucketing shows band/threshold daily separately
