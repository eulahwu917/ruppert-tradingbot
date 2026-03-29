# Developer Fix: Source Misclassification in Closed Trades Table
_SA-3 Developer — 2026-03-12_

---

## Problem

Three crypto trades (KXETH and KXXRP series) were displaying as **MANUAL** in the closed trades table when they should display as **BOT**.

## Root Cause

**File:** `dashboard/templates/index.html` — `loadTrades()` function (line ~836 before fix)

The source classification array in the closed trades renderer incorrectly included `'crypto'`:

```javascript
// BUG: 'crypto' was in the MANUAL list
const src = (['geo','gaming','manual','crypto'].includes(t.source))
  ? '<span class="b-manual">MANUAL</span>'
  : '<span class="b-bot">BOT</span>';
```

Since KXETH/KXXRP entry records have `source='crypto'`, they matched the MANUAL condition and were displayed as MANUAL.

**The `exit_type` field was a red herring for api.py** — `api.py` does not use `exit_type` for source classification. The frontend also doesn't read `exit_type` for classification. The real bug was `'crypto'` being incorrectly listed as a MANUAL source in the frontend.

## Fix

**File changed:** `dashboard/templates/index.html`

Two locations fixed (both now consistent):

1. **Closed Positions table (`loadTrades()`)** — removed `'crypto'` and `'gaming'` from MANUAL list; added `'economics'`
2. **Active Positions table (`loadPositions()`)** — removed `'gaming'` (which was removed from system); added `'economics'`

### Classification now applied consistently:
- **MANUAL:** `['economics', 'geo', 'manual']`
- **BOT:** everything else (bot, weather, crypto)

## Files Modified

- `dashboard/templates/index.html` — 2 lines changed

## Files NOT Changed

- `dashboard/api.py` — already correct. `get_pnl()` uses `src in ('economics', 'geo', 'manual')` correctly. `get_trades()` preserves original `source` field from entry records without override.

## Git Status

- Staged: `git add dashboard/templates/index.html`
- NOT pushed (awaiting CEO review per rules)

## TODO / Notes

- QA should verify dashboard displays KXETH and KXXRP as BOT after restart
- `economics` was also missing from active positions source classifier — fixed as part of this PR
- SA-3 fixed line 792 in loadPositions() open P&L loop: changed ['geo','gaming','manual'] ? ['economics','geo','manual']; git staged (no push). 2026-03-12.
