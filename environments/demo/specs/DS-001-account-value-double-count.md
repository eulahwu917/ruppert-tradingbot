# SPEC DS-001 — Account Value Double-Count Bug Fix
**Version:** 2.0 (Revised)
**Author:** Data Scientist
**Date:** 2026-03-29
**Status:** READY FOR DEV

---

## Problem Statement

The dashboard's **Account Value** display is inflated because `closed_pnl` is counted twice.

### Root Cause

`_build_state()` sets:
```
account.balance = get_capital()  # = deposits + closed_pnl (correct current capital)
account.closed_pnl = <sum from settle/exit records>  # the same closed_pnl, returned separately
```

The frontend then computes:
```js
// renderState() — line ~1111
Account Value = acct.balance + acct.open_pnl + acct.closed_pnl
             = (deposits + closed_pnl) + open_pnl + closed_pnl   ← closed_pnl counted twice
```

Same double-count exists in `updateAccountValue()`:
```js
// line ~894
document.getElementById('av').textContent = dollar(base + openPnl + closedPnl);
// base = window._kalshiBalance = acct.balance = get_capital() = deposits + closed_pnl
```

### What Is Correct

```
Account Value = deposits + closed_pnl + open_pnl
             = get_capital()           + open_pnl
             = acct.balance            + acct.open_pnl
```

`closed_pnl` is already baked into `balance`. It must not be added again.

---

## Chosen Fix — Option B: Frontend Formula Change

**Change 2 frontend JS lines. No backend changes. No API contract changes.**

### Why Option B

| Option | Lines Changed | Risk |
|--------|--------------|------|
| A — Set `account.closed_pnl = 0` in `_build_state()` | 1 backend | Breaks the Closed P&L display widget which reads `acct.closed_pnl` for its own separate tile — would need additional patching to restore |
| **B — Drop `+ closed_pnl` from frontend formula** | **2 frontend** | **Zero backend risk. Closed P&L tile reads `acct.closed_pnl` separately and is unaffected.** |
| C — Set `balance = get_raw_deposits()` in `_build_state()` | 1 backend + downstream audit | Requires verifying every consumer of `balance` field; highest regression surface |

Option B changes the fewest lines and has the lowest regression risk.

---

## Required Changes

### File: `environments/demo/dashboard/templates/index.html`

#### Change 1 — `renderState()` (~line 1111)

**Before:**
```js
// Account Value = balance + open P&L + closed P&L
$('av').textContent = dollar((acct.balance||0) + (acct.open_pnl||0) + (acct.closed_pnl||0));
```

**After:**
```js
// Account Value = balance + open P&L
// balance = get_capital() = deposits + closed_pnl (closed_pnl already included)
$('av').textContent = dollar((acct.balance||0) + (acct.open_pnl||0));
```

#### Change 2 — `updateAccountValue()` (~line 894)

**Before:**
```js
function updateAccountValue() {
  // Single source of truth: $400 base + open P&L + closed P&L
  const base     = window._kalshiBalance || 400;
  const openPnl  = window._openPnl  || 0;
  const closedPnl= window._closedPnl || 0;
  document.getElementById('av').textContent = dollar(base + openPnl + closedPnl);
}
```

**After:**
```js
function updateAccountValue() {
  // Account Value = balance + open P&L
  // balance (window._kalshiBalance) = get_capital() = deposits + closed_pnl already included
  const base    = window._kalshiBalance || 400;
  const openPnl = window._openPnl  || 0;
  document.getElementById('av').textContent = dollar(base + openPnl);
}
```

---

## No Backend Changes Required

- `get_capital()` — **do not touch**
- `_build_state()` — **do not touch**
- `account.balance` field — **do not touch**
- `account.closed_pnl` field — **do not touch** (still needed by the Closed P&L tile)
- `capital.py` — **do not touch**

---

## What Is NOT Changed

- The **Closed P&L tile** (`cpnl`) reads `acct.closed_pnl` directly and is unaffected by this fix.
- The **Buying Power** calculation (`balance - deployed`) is unaffected.
- The **P&L endpoint** (`/api/pnl`) is unaffected.
- The **`/api/account` endpoint** is unaffected.
- Live mode behavior is unaffected (same formula applies; `balance` in live mode would be Kalshi's balance which also reflects settled positions).

---

## Verification

After applying the fix, confirm:

1. **Account Value displayed** = `balance + open_pnl` (matches manual calculation)
2. **Closed P&L tile** still shows correct closed P&L (reads its own field, not Account Value)
3. **No flash/jump** on page load — `updateAccountValue()` still uses same `window._kalshiBalance` timing
4. **Manual check:** If deposits = $400, closed_pnl = +$50, open_pnl = +$10:
   - `balance` = $450 (from `get_capital()`)
   - Expected Account Value = $450 + $10 = **$460**
   - Old (buggy) formula: $450 + $10 + $50 = $510 (wrong)
   - New (fixed) formula: $450 + $10 = **$460** (correct)

---

## Notes

- The comment `// DEMO: Account Value = $400 starting capital + Open P&L + Closed P&L` on line ~712 should also be updated to reflect the correct formula, as it may mislead future developers. (Non-blocking — cosmetic only.)
- This bug likely appeared when `closed_pnl` was added as a separate returned field from `_build_state()` without recognizing that `balance` = `get_capital()` already includes it.
