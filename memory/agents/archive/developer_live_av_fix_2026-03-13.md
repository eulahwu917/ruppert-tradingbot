# Developer Fix: Live Dashboard Account Value = $0.00
_Applied: 2026-03-13 by SA-2 Developer_

## Problem
LIVE dashboard (`ruppert-tradingbot-live/dashboard/templates/index.html`) showed Account Value as $0.00 while Buying Power correctly showed $172.37.

**Root cause**: `updateAccountValue()` fired (from `loadLivePrices` and `loadClosedPnl`) before `loadAccount()` completed, so `window._buyingPower` was never set — it was `undefined`, causing `base` to fall through to 0. Additionally, `closedPnl` was being double-counted in the formula (buying power already includes it).

## Changes Made

### Change 1 — `loadAccount()`: Set `window._buyingPower` and call `updateAccountValue()` immediately after BP is computed

**File**: `ruppert-tradingbot-live/dashboard/templates/index.html`

**Before**:
```javascript
$('bp').textContent = dollar(Math.max(realBuyingPower, 0));
// NOTE: bot-dep, man-dep, bot-cnt, man-cnt are set by loadClosedPnl() from /api/pnl
```

**After**:
```javascript
$('bp').textContent = dollar(Math.max(realBuyingPower, 0));
window._buyingPower = Math.max(realBuyingPower, 0);
updateAccountValue();
// NOTE: bot-dep, man-dep, bot-cnt, man-cnt are set by loadClosedPnl() from /api/pnl
```

### Change 2 — `updateAccountValue()`: Remove double-counted `closedPnl`

**Before**:
```javascript
function updateAccountValue() {
  // LIVE: Account Value = Buying Power + Open P&L (buying power already includes closed P&L)
  const base     = window._buyingPower || window._kalshiBalance || 0;
  const openPnl  = window._openPnl  || 0;
  const closedPnl= window._closedPnl || 0;
  document.getElementById('av').textContent = dollar(base + openPnl + closedPnl);
}
```

**After**:
```javascript
function updateAccountValue() {
  // LIVE: Account Value = Buying Power + Open P&L
  // Buying power already includes closed P&L, so don't add it again
  const base    = window._buyingPower || window._kalshiBalance || 0;
  const openPnl = window._openPnl || 0;
  document.getElementById('av').textContent = dollar(base + openPnl);
}
```

## Expected Result
Account Value will now show Buying Power ($172.37) + Open P&L, updated immediately when `loadAccount()` completes (no more timing race). Closed P&L is no longer double-counted.
