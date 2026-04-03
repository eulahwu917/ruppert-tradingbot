# Spec: Open P&L Percentage Uses Wrong Denominator

**Date:** 2026-03-30  
**Author:** Trader (Ruppert)  
**Severity:** Low (display only) — P&L dollar value is correct; only the percentage is misleading  
**File:** `environments/demo/dashboard/templates/index.html`  
**Line:** ~1115

---

## Problem Statement

The Open P&L percentage shown in the dashboard header is computed as:

```
Open P&L % = open_pnl / open_cost
```

Where `open_cost` is the total capital currently deployed in open positions that have live prices. This produces a **per-position return rate** — how much the open positions have moved relative to what was deployed in them.

David wants Open P&L % to reflect **return on total capital** — i.e., how much the unrealized gain/loss represents as a fraction of total account balance. This is the standard "account-level" view.

---

## Affected Line

**`environments/demo/dashboard/templates/index.html`, ~line 1115:**

```javascript
setPnl('opnl', 'opnl-pct', acct.open_pnl || 0, acct.open_cost || 0);
```

The `setPnl(mainId, pctId, val, cost)` function signature (defined ~line 725) computes:
```
pct = val / cost * 100
```

So the fourth argument (`cost`) is the denominator for the percentage. Currently `acct.open_cost` is passed — capital deployed in open positions. The fix replaces this with `acct.balance` — total account balance.

---

## BEFORE

```javascript
// Open P&L
setPnl('opnl', 'opnl-pct', acct.open_pnl || 0, acct.open_cost || 0);
```

**Effect:** Open P&L % = `open_pnl / open_cost` → return rate on deployed capital only.

---

## AFTER

```javascript
// Open P&L
setPnl('opnl', 'opnl-pct', acct.open_pnl || 0, acct.balance || 0);
```

**Effect:** Open P&L % = `open_pnl / balance` → return rate on total account capital.

---

## Rationale

Showing Open P&L as a percentage of `open_cost` inflates the displayed percentage when only a fraction of the account is deployed. For example:

| Scenario | open_pnl | open_cost | balance | Before (% of open_cost) | After (% of balance) |
|----------|----------|-----------|---------|--------------------------|----------------------|
| 10% deployed | +$5 | $50 | $500 | +10.0% | +1.0% |
| 100% deployed | +$5 | $500 | $500 | +1.0% | +1.0% |

The "After" figure is consistent regardless of deployment level and matches what David expects: a true account-level return on open positions. This also aligns with how Closed P&L % is computed (~line 1125), which already uses `acct.balance` as its denominator.

---

## Testing Checklist

- [ ] Open P&L % header shows `open_pnl / balance * 100`, not `open_pnl / open_cost * 100`
- [ ] When account is partially deployed (e.g., $100 of $1000 in positions), Open P&L % is visibly smaller than before
- [ ] When `acct.balance` is 0 or null, `setPnl` handles gracefully (no divide-by-zero display error — verify `setPnl` guards against zero denominator)
- [ ] Closed P&L % is unaffected
- [ ] Dollar Open P&L value is unaffected
