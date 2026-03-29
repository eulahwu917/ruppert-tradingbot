# SA-3 Developer — Trades Count Fix + Label Rename
_Date: 2026-03-12_
_Commit: a50a78b_

---

## Task Summary

Two fixes to the P&L dashboard split cards (Bot Trades / Manual Trades).

---

## Fix 1 — Label Renames (index.html)

Changed in both Bot and Manual split cards:
- `"Deployed"` → `"Open Capital Deployed"` (max-width updated: 60px → 110px)
- `"Trades"` → `"Total Trades"` (max-width updated: 60px → 70px)

---

## Fix 2 — Trades Count Bug (index.html only)

### Root Cause

**Pure frontend bug.** `api.py` was correct; the source classification and counting in `get_pnl_history()` worked perfectly.

The bug: `loadAccount()` overwrote `bot-cnt` and `man-cnt` *after* `loadClosedPnl()` had already set them correctly.

### Execution Flow (before fix)
```
loadAll()
  └─ await loadClosedPnl()        ← Sets bot-cnt=8, man-cnt=3  ✅ (from /api/pnl)
  └─ Promise.all([
       loadAccount(),             ← Overwrites bot-cnt=4, man-cnt=0  ❌
       ...
     ])
```

### Why `/api/account` returned wrong counts

`get_account()` builds `trades` by filtering out all tickers present in the `exited` set (action='exit'). Since 11 of 15 unique tickers have exit records, only 4 non-exited ones remain (all bot): `KXHIGHMIA-26MAR10-B84.5`, `KXHIGHMIA-26MAR11-B83.5`, `KXETH-26MAR1117-B2030`, `KXETH-26MAR1117-B2070`. Result: `bot_trade_count=4, manual_trade_count=0`.

### Actual trade data (from logs)

| Ticker | Type | Has Exit Record | Source |
|--------|------|----------------|--------|
| KXHIGHMIA-26MAR11-B85.5 | Weather | ✅ Yes | weather → **bot** |
| KXHIGHNY-26MAR11-B66.5 | Weather | ✅ Yes | weather → **bot** |
| KXHIGHCHI-26MAR11-B52.5 | Weather | ✅ Yes | weather → **bot** |
| KXHIGHCHI-26MAR11-B50.5 | Weather | ✅ Yes | weather → **bot** |
| KXHIGHCHI-26MAR11-B48.5 | Weather | ✅ Yes | weather → **bot** |
| KXHIGHMIA-26MAR11-B83.5 | Weather | ❌ No (settled by date) | → **bot** (API call) |
| KXETH-26MAR1217-B2100 | Crypto | ✅ Yes | crypto → **bot** |
| KXXRP-26MAR1217-B1.4099500 | Crypto | ✅ Yes | crypto → **bot** |
| KXETH-26MAR1217-B2140 | Crypto | ✅ Yes | crypto → **bot** |
| KXCPI-26JUN-T0.0 | CPI/Manual | ✅ Yes | manual → **manual** |
| KXCPI-26NOV-T0.3 | CPI/Manual | ✅ Yes | manual → **manual** |
| KXCPI-26AUG-T0.3 | CPI/Manual | ✅ Yes | manual → **manual** |
| KXHIGHMIA-26MAR10-B84.5 | Weather | ❌ No (settled by date) | → **bot** (API call) |
| KXETH-26MAR1117-B2030 | ETH | ❌ No (settled by date) | → **bot** (API call) |
| KXETH-26MAR1117-B2070 | ETH | ❌ No (settled by date) | → **bot** (API call) |

Expected from `/api/pnl`: **~8 bot** (from exit records) **+ 3 manual** = correct.

### CPI Source Classification — No Bug Found

Checked as requested: CPI entry records have `source='manual'`, exit records also `source='manual'`. The code reads from exit record first (`exit_records[ticker].get('source', ...)`), returns 'manual', `is_manual=True`. Classification was always correct. ✅

### Fix Applied

Removed two lines from `loadAccount()` in `index.html`:
```javascript
// REMOVED:
$('bot-cnt').textContent = acct.bot_trade_count || 0;
$('man-cnt').textContent = acct.manual_trade_count || 0;
```

`bot-cnt` and `man-cnt` are now exclusively owned by `loadClosedPnl()` which reads from `/api/pnl` — the correct source for closed trade counts.

---

## Files Changed

- `dashboard/templates/index.html` — label renames + removed overwriting lines
- `dashboard/api.py` — **no changes** (logic was correct)

## Files NOT Changed (api.py is clean)

`get_pnl_history()` source classification is correct. `closed_count_by_source` increments happen after the exit-record branch (no `continue` risk for exit-record trades). Verified OK.

---

## For QA Review

1. Bot card: labels now read "Open Capital Deployed" and "Total Trades"
2. Manual card: same label renames
3. Bot count should now show ~8+ (all exit-record bot trades + API-fetchable settled ones)
4. Manual count should now show 3 (CPI trades: JUN, NOV, AUG 2026)
5. No regressions expected — `loadClosedPnl()` already set these correctly before; `loadAccount()` no longer corrupts them
