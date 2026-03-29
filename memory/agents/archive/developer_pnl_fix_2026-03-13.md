# Developer Summary — Module Card P&L Fix
_Date: 2026-03-13 | SA-3 Developer_

## Task
Fix module card P&L to use the same data source as the closed positions table.

## Problem
In `get_pnl_history()`, the per-module P&L breakdown was computed inside the
`settled_tickers` loop using Kalshi API settlement prices. The closed positions
table (`get_trades()`) also calls Kalshi API but with slightly different P&L
computation logic — this caused the two to diverge and display different numbers
for the same trades.

## Fix Applied
**File:** `kalshi-bot/dashboard/api.py` — `get_pnl_history()`

**Removed:** The per-module accumulation block that was embedded inside the
`settled_tickers` loop (accumulated `module_stats` from Kalshi API settlement data).

**Added:** A new standalone section after the settled_tickers loop that calls
`get_trades()` directly and aggregates `realized_pnl` by module. This guarantees
module card totals are computed from **identical data** as the closed positions table.

```python
_closed_trades = get_trades()
for _ct in _closed_trades:
    _mod = _ct.get('module', 'other')
    _rpnl = float(_ct.get('realized_pnl') or 0.0)
    # accumulate closed_pnl, trade_count, wins, closed_pnl_month, closed_pnl_year
```

**Why `get_trades()` not raw exit records:**
- Exit records in JSONL only exist for positions the bot actively exited (95¢ rule, stop-loss).
- Naturally settled losses have NO exit record — they're processed via Kalshi API in `get_trades()`.
- Using raw exit records would have missed these losses entirely. `get_trades()` covers both cases.

**Account-level `closed_pnl`** (top-level in API response) still comes from
Kalshi settled positions / pnl_cache — unchanged. The ~$1.96 gap between
account-level P&L ($87.33) and sum of module P&Ls ($85.37) is expected and
acceptable (Kalshi P&L not in trade logs).

## What Was NOT Changed
- Account-level `closed_pnl` computation (Kalshi API / pnl_cache)
- `open_pnl`, `open_by_source`, per-module open stats — untouched
- `get_trades()` itself — not modified
- `pnl_cache.json` write — untouched
- All other endpoints — untouched

## First Attempt (Reverted)
Initial implementation used raw JSONL exit records (`realized_pnl` field from
`action=exit` records). CEO correctly identified this only captures actively-exited
positions, not settled losses. Reverted and replaced with `get_trades()` approach.

## Git
- Staged: `git add dashboard/api.py`
- Not pushed (CEO pushes EOD per team rules)

## Status
Ready for QA review.
