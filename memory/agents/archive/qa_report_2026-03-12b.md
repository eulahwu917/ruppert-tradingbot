# QA REPORT — CEO Hotfix Re-Review (2026-03-12)

**Reviewer:** SA-4 QA  
**Files reviewed:**
- `kalshi-bot/dashboard/api.py`
- `kalshi-bot/dashboard/templates/index.html`

**Status: PASS WITH WARNINGS**

---

## ✅ Checks Passed

- **Buying power formula is mathematically correct** — `starting_capital + closed_pnl - total_deployed` is the right formula. Fallback `|| 0` guards prevent crashes when values are undefined.
- **`is_settled_ticker()` UTC-4 offset is correct for March 2026** — DST began March 8, so Eastern time is EDT (UTC-4). The `% 24` handles midnight modulo wrapping in principle.
- **`closed_pnl_realized = 0.0` is NOT referenced anywhere else** — confirmed it only appears on line 278 of `api.py`. It is dead code but does not cause any wrong calculations.
- **`if (true)` block: Account Value math is correct when NO positions exist** — `loadLivePrices()` is only called if positions array is non-empty (early return in `loadPositions()` line ~467). `window._openPnl` stays `undefined`, but `updateAccountValue()` uses `window._openPnl || 0`, which correctly resolves to `0`. Account Value math is sound.
- **No hardcoded API keys, no secrets exposed, no files outside `kalshi-bot/` modified.**
- **No `bare except:` blocks introduced; all try/except have appropriate pass.**

---

## ⚠️ Warnings (Discretionary — No Crashes, No Data Loss)

### W1 — `index.html` — Buying Power Race Condition (Real Bug, Low Severity in Demo)

**Location:** `index.html` — `loadAll()` and `loadAccount()` / `loadClosedPnl()`

`loadAll()` runs `loadAccount()` and `loadClosedPnl()` in **parallel** via `Promise.all`. `loadAccount()` computes:
```javascript
const realBuyingPower = (acct.starting_capital || 400) + (window._closedPnl || 0) - (acct.total_deployed || 0);
```
If `loadAccount()` resolves **before** `loadClosedPnl()` sets `window._closedPnl`, the closed P&L term is `0`, and Buying Power is understated (shows `starting_capital - deployed`, missing closed gains/losses).

**Critical gap:** `loadClosedPnl()` calls `updateAccountValue()` at the end (which correctly updates Account Value), but it does **not** re-trigger the buying power calculation. Buying Power stays stale until the next standalone `loadAccount()` call (runs at 35s interval). On every 30s `loadAll()` cycle, this race condition recurs — buying power is typically wrong for the first few seconds of every refresh.

**Fix suggestion:** At the end of `loadClosedPnl()`, after setting `window._closedPnl`, also re-run the buying power display:
```javascript
// After updateAccountValue() in loadClosedPnl():
const acctDeploy = window._lastAcctDeployed || 0;  // cache acct.total_deployed in loadAccount()
const bp = (window._kalshiBalance || 400) + (window._closedPnl || 0) - acctDeploy;
$('bp').textContent = dollar(Math.max(bp, 0));
```
Or simpler: serialize `loadClosedPnl()` to run after `loadAccount()` completes.

**Risk in demo:** Low. Self-corrects within 35s. No money at risk.

---

### W2 — `index.html` — Open P&L Display Stays `--` When No Positions

**Location:** `index.html` — `loadPositions()` early return (line ~467)

When `positions` array is empty, `loadPositions()` does an early `return` before calling `loadLivePrices()`. The `#opnl` account bar element is never updated — it stays showing `--` instead of `$0.00`.

`window._openPnl` is never set to `0` explicitly in this path (stays `undefined`), but `updateAccountValue()` handles this correctly via `|| 0`. So **Account Value is correct** — this is a display-only issue in the Open P&L cell.

**Fix suggestion:** In the empty-positions branch of `loadPositions()`, add:
```javascript
window._openPnl = 0;
setPnl('opnl', 'opnl-pct', 0, 1);
updateAccountValue();
```

---

### W3 — `api.py` Line 278 — Dead Variable `closed_pnl_realized = 0.0`

**Location:** `api.py` line 278, inside the `else` (demo mode) branch of `get_account()`

```python
closed_pnl_realized = 0.0  # frontend adds closed P&L from /api/pnl
```

This variable is assigned but never used again — not returned in the dict, not referenced anywhere else in the function or file. It is pure dead code, a leftover from a reverted approach. No wrong calculations result from it, but it is confusing (the comment implies it was once returned or used).

**Confirmed:** Only one occurrence in the entire file (line 278).

**Fix suggestion:** Delete this line on next Developer pass.

---

### W4 — `api.py` Line 189 — Dead Import `import time as _time` Inside `is_settled_ticker()`

**Location:** `api.py` line 189, inside `is_settled_ticker()` same-day hour block

```python
import time as _time
now_hour_edt = (_dt.utcnow().hour - 4) % 24
```

`_time` is imported but never used. The function only calls `_dt.utcnow()` directly. This is a dead import — harmless but should be removed.

---

### W5 — `api.py` Lines 281–293 — Duplicate Dict Keys in `get_account()` Return

**Location:** `api.py` return dict in `get_account()`

Two keys appear twice each:
- `"starting_capital"` — line 281 (unrounded `STARTING_CAPITAL`) and line 288 (`round(STARTING_CAPITAL, 2)`)
- `"bot_deployed"` — line 283 (`round(bot_cost, 2)`) and line 293 (`round(bot_cost, 2)`)

In Python dicts, the **last value wins**. Both cases result in the rounded value, which is correct. Benign, but indicates the CEO edited this return dict without cleaning up the original keys.

---

### W6 — `api.py` `is_settled_ticker()` — Midnight Crossover Edge Case (3-Hour Window)

**Location:** `api.py` lines 186–192 — same-day hour check in `is_settled_ticker()`

```python
now_hour_edt = (_dt.utcnow().hour - 4) % 24
if now_hour_edt >= hour:
    return True
```

The server is in PDT (UTC-7). Between **9pm–midnight PDT** (= midnight–3am EDT), the `% 24` wraps `now_hour_edt` to `0–2`. Any intraday settlement hour (e.g., `17` for 5pm EDT) would then fail the `>= hour` check, causing the function to return `False` — incorrectly treating an already-settled ticker as still open.

**Practical impact:** For tickers with time components (e.g., `26MAR1217`), during the 9pm–midnight PDT window, recently-settled positions would not be flagged as settled, potentially appearing in open positions or being included in deployed capital. Duration: 3 hours/night. **Does not affect all-day settlement tickers** (those without an hour component).

**Root cause:** The `mkt_date < today` check uses the PDT date, but the hour comparison uses EDT. These two reference frames diverge by 3 hours each night.

**Fix suggestion:** Compare `now_hour_edt` to `hour`, and also handle the case where `now_hour_edt < hour` but the EDT date has already rolled past `mkt_date`. The cleanest fix is to compare full `datetime` objects in a single timezone rather than mixing local date + EDT hour.

---

### W7 — `api.py` `is_settled_ticker()` — UTC-4 Hardcoded (EST/EDT Not Handled)

**Location:** `api.py` line 190

The comment says "EDT (UTC-4)" but the offset is hardcoded as `-4`. Kalshi markets use Eastern Time:
- Mar–Nov (DST active): EDT = UTC-4 ✅ **correct today**
- Nov–Mar (DST inactive): EST = UTC-5 ❌ **would be wrong in winter**

This code was added today for demo mode. In demo mode until March 14, the risk is minimal. However if this runs in winter without a fix, same-day settled tickers could be incorrectly treated as unsettled for 1 hour each day.

---

## Issues Summary

| # | Severity | File | Location | Description |
|---|----------|------|----------|-------------|
| W1 | Medium | index.html | `loadAccount()` / `loadClosedPnl()` | Buying power race condition — stale for up to 35s |
| W2 | Low | index.html | `loadPositions()` empty branch | Open P&L display shows `--` instead of `$0.00` when no positions |
| W3 | Low | api.py | Line 278 | `closed_pnl_realized = 0.0` dead variable |
| W4 | Low | api.py | Line 189 | `import time as _time` dead import |
| W5 | Low | api.py | Lines 281–293 | Duplicate dict keys in `get_account()` return |
| W6 | Medium | api.py | `is_settled_ticker()` | Midnight crossover: 9pm–midnight PDT tickers may show as open for 3h/night |
| W7 | Low | api.py | `is_settled_ticker()` line 190 | UTC-4 hardcoded — EST (winter) would be off by 1h |

---

## Verdict

**Safe to keep for current demo mode.** No crashes, no data loss, no security issues, no wrong trade sizing.

**W1 (buying power race) and W6 (midnight crossover) should be fixed before live trading.** W6 in particular could cause incorrect `total_deployed` calculations if a settled market isn't recognized as settled during the 9pm–midnight PDT window.

**W3, W4, W5** are cleanup items — assign to SA-3 Developer on next pass.

---

*QA review completed: 2026-03-12*
