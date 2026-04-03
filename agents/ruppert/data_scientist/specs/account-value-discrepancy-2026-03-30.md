# Account Value Discrepancy — Root Cause Spec
**Date:** 2026-03-30  
**Author:** Data Scientist  
**Status:** Root Cause Confirmed — Awaiting Dev Fix

---

## Observed Facts

| Field | Displayed Value |
|---|---|
| Initial Capital | $10,000.00 |
| Open P&L | −$714.45 |
| Closed P&L | −$450.27 |
| Account Value | $8,753.59 |

**Expected Account Value** (if formula = Initial + Open P&L + Closed P&L):  
`$10,000 + (−$714.45) + (−$450.27) = $8,835.28`

**Actual gap:** $8,835.28 − $8,753.38 = **+$81.90**

---

## Root Cause

### The Stale `pnl_cache.json` Double-Count Problem

There are **two separate closed P&L computations** in the dashboard that are **out of sync**:

### Source 1: `get_capital()` in `capital.py`
```
get_capital() = sum(demo_deposits.jsonl) + pnl_cache.json["closed_pnl"]
             = $10,000 + (−$532.17)
             = $9,467.83
```
This value is stored as `window._kalshiBalance` in the frontend.

### Source 2: `/api/state` → `_build_state()` in `api.py`
Computes `closed_pnl` **live** from all trade log files (settle/exit records):
```
closed_pnl (live from trade logs) = −$450.27
```

### The Frontend Formula
```javascript
// In renderState() — index.html
Account Value = acct.balance + acct.open_pnl
              = get_capital()  + open_pnl
              = $9,467.83      + (−$714.45)
              = $8,753.38
```

### Why the Gap Exists

At the time of observation, `pnl_cache.json` had **not yet been updated** to include the most recently settled/exited trade:

| Record | Ticker | P&L |
|---|---|---|
| exit (2026-03-30) | `KXDOGE15M-26MAR301700-00` | **+$81.90** |

**Cumulative settled P&L progression (from trade logs):**
- After `KXXRP15M-26MAR301645-45` exit: −$532.17 ← **this was pnl_cache.json's stale value**
- After `KXDOGE15M-26MAR301700-00` exit: −$450.27 ← **this is what /api/state's _build_state() computed live**

`pnl_cache.json` had value `−532.17` but the live calculation in `_build_state()` computed `−450.27`.

**Gap = −$450.27 − (−$532.17) = +$81.90 exactly.**

### Why Account Value Is Too Low
`get_capital()` used the stale `pnl_cache.json` value (`−$532.17`) to compute the account balance.  
The Closed P&L display used the live trade-log computation (`−$450.27`).  
These two paths diverge whenever `pnl_cache.json` is behind the trade logs.

### Code Paths
```
Account Value = window._kalshiBalance + window._openPnl
                         ↓
             = acct.balance (from /api/state)
                         ↓
             = STARTING_CAPITAL (from get_capital())  ← uses pnl_cache.json
                         ↓
             = deposits + pnl_cache.json["closed_pnl"]  ← stale

Closed P&L   = acct.closed_pnl (from /api/state)
                         ↓
             = _build_state() → live scan of trade log files  ← current
```

---

## BEFORE (Broken State)

```
Account Value = get_capital() + open_pnl
             = (deposits + pnl_cache.closed_pnl) + open_pnl

Closed P&L   = _build_state().closed_pnl   # live, from trade logs
```

**Problem:** `get_capital()` uses `pnl_cache.json` (written by synthesizer, may lag trade logs by minutes). `_build_state()` reads trade logs directly. Any window of time between the last exit record being written to a trade log and the next synthesizer run causes the Account Value to be wrong by the P&L of the unsynthesized exit.

---

## AFTER (Fixed State)

**Option A — Preferred (consistent formula):**

Remove `closed_pnl` from `get_capital()`. The account balance base should be deposits only. The closed P&L is already added by the frontend when it computes Account Value.

In `capital.py`, `get_capital()` returns:
```python
# AFTER: base capital = deposits only (no closed P&L baked in)
return round(total, 2)
```

In `api.py`, `_build_state()` computes account balance as:
```python
'balance': round(STARTING_CAPITAL, 2),  # deposits only
```

Frontend formula (no change needed — already correct if balance = deposits only):
```javascript
// Account Value = balance + closed_pnl + open_pnl
// But currently: Account Value = balance + open_pnl
// → AFTER: balance must = deposits only, and Account Value must also add closed_pnl
$('av').textContent = dollar((acct.balance || 0) + (acct.closed_pnl || 0) + (acct.open_pnl || 0));
```

**Option B — Alternative (keep pnl_cache path, fix synchronization):**

In `_build_state()`, compute `STARTING_CAPITAL` using the same live closed P&L scan that feeds `closed_pnl`. This guarantees they are always in sync:

```python
# AFTER: derive balance from live closed_pnl (already computed above)
balance = round(deposits + closed_pnl_total, 2)
```

And remove `get_capital()` from the `_build_state()` code path (only use it for buying power calculation, not as the Account Value base).

---

## Recommended Fix: Option A

**Rationale:** The frontend `renderState()` function already receives both `acct.balance` and `acct.closed_pnl` from `/api/state`. Account Value should be computed as `balance + closed_pnl + open_pnl` where `balance = deposits`. This is semantically clean, avoids the two-source problem entirely, and makes the arithmetic on the dashboard verifiable by the user: `Initial + Closed P&L + Open P&L = Account Value`.

**Files to change:**
1. `agents/ruppert/data_scientist/capital.py` — `get_capital()`: remove `closed_pnl` addition
2. `environments/demo/dashboard/api.py` — `_build_state()`: change `account.balance` to be `deposits` only (remove `get_capital()` or call it without the closed P&L addition); also update `/api/account`
3. `environments/demo/dashboard/templates/index.html` — `renderState()`: update Account Value formula to `acct.balance + acct.closed_pnl + acct.open_pnl`

**Buying Power** must remain: `deposits − total_deployed` (not affected by closed P&L — correct behavior).

---

## Verification Steps (for QA)

1. Confirm `pnl_cache.json` closed_pnl ≠ live closed_pnl computed from trade logs → gap exists before fix
2. Apply fix; reload dashboard
3. Confirm: `Account Value = Initial Capital + Closed P&L + Open P&L` within ±$0.01
4. Confirm: `Buying Power = Initial Capital − total_deployed` (unchanged)
5. Confirm: gap is $0.00 even immediately after a new exit record is written to trade logs (before synthesizer runs)

---

## Summary

**Root cause:** `get_capital()` bakes `pnl_cache.json`'s closed P&L into the "balance" figure, while the dashboard's Closed P&L display reads directly from trade logs. These two sources can diverge by up to one unsynthesized exit's P&L for as long as the synthesizer has not run. At the time of observation, the gap was exactly **$81.90**, matching the most recent unsynthesized exit record (`KXDOGE15M-26MAR301700-00`, pnl=+$81.90). The fix is to ensure Account Value uses a single consistent source for closed P&L — the live trade-log computation already used by `_build_state()`.
