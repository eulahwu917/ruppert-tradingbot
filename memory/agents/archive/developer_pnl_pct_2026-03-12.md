# Developer P&L % Bug Fix — 2026-03-12

**Agent:** SA-3 Developer  
**Commit:** `ef029e5`  
**Status:** STAGED — awaiting QA review and CEO approval before push

---

## Bug Summary

The Bot and Manual split cards on the dashboard were showing P&L percentages like **+67200%** and **+670%** — clearly wrong.

---

## Root Cause

In `index.html`'s `loadClosedPnl()`, `setSplitPnl()` was called with `pnl.bot_deployed||1` as the cost denominator:

```javascript
setSplitPnl('bot-pnl', 'bot-pnl-pct', ..., pnl.bot_deployed||1);
```

**`bot_deployed` is the OPEN deployed capital** — it reflects what's currently staked in open positions. When all positions are closed (settled), `bot_deployed = 0`. The `||1` fallback replaces it with `1`, turning the formula into:

```
pp = pnl_dollars / 1 * 100  →  $6.72 / 1 * 100 = 672%
                              →  $672 / 1 * 100 = 67200%
```

This was **not** a cents/dollars mismatch or a double-multiplication. It was a zero-denominator fallback using the wrong column entirely.

---

## Fix

### `dashboard/api.py` — `get_pnl_history()`

- Added `bot_cost_basis = 0.0` and `manual_cost_basis = 0.0` initialisation
- In the settled/exited positions loop: accumulate `t['size_dollars']` into the appropriate cost basis bucket (bot vs manual), using the same `is_manual` classification already in place
- Added `bot_cost_basis` and `man_cost_basis` to the `/api/pnl` response

### `dashboard/templates/index.html`

1. **Fixed `setSplitPnl()` denominator**: changed from `pnl.bot_deployed||1` → `pnl.bot_cost_basis` and `pnl.man_cost_basis`
2. **Added near-zero guard**: if `cost < 0.01`, display `N/A` instead of a giant number
3. **Added ±999% cap**: `pp = Math.max(-999, Math.min(999, pp))` — if capped, appends `*` to the display value

---

## Files Changed

| File | Change |
|------|--------|
| `dashboard/api.py` | +15 lines: cost basis accumulation + response fields |
| `dashboard/templates/index.html` | +20 lines: fixed denominator + N/A guard + ±999% cap |

---

## What Was NOT Changed

- No trading logic touched
- No secrets/ directory
- No `.gitignore`
- No `git push` — CEO must review before pushing

---

## Remaining Notes

- The `setSplitPnl` timeframe dropdowns (Month / Year / All Time) use the same `bot_cost_basis` / `man_cost_basis` total for all periods, which is an approximation (all-time cost basis used even for monthly view). If more granular accuracy is needed in future, we'd need period-sliced cost basis from the API as well. For now this is a significant improvement over the `||1` fallback.
