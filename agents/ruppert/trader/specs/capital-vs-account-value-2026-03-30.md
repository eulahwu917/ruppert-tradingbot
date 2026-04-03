# Spec: Capital vs Account Value — Definition Audit
**Date:** 2026-03-30
**Author:** Data Scientist
**Status:** No bug — intentional architectural difference. Documentation only.

---

## Observed Discrepancy

From the 3pm scan notification:
- **Capital: $11,294.41**

From the dashboard:
- **Account Value: $9,724.92**

Gap: **$1,569.49**

These are NOT the same concept. The gap is expected and correct. Both numbers are computed correctly for their respective purposes.

---

## What "Capital" Means in Notifications

Source: `ruppert_cycle.py` (all scan modes: full, weather_only, crypto_only)

```python
_capital  = get_capital()
_deployed = get_daily_exposure()
_bp       = get_buying_power()
_cap_line = f'${_capital:.2f} | Deployed: ${_deployed:.2f} | BP: ${_bp:.2f}'
```

`get_capital()` is defined in `agents/ruppert/data_scientist/capital.py`:

```
Capital = sum(demo_deposits.jsonl) + compute_closed_pnl_from_logs()
```

- **Deposits component:** All entries in `environments/demo/logs/demo_deposits.jsonl`
- **Closed P&L component:** Realized gains/losses from all settled/exited trades, read live from trade logs (NOT from pnl_cache.json, which can lag)

This is the **total portfolio base** — the foundation from which all position sizing, daily caps, and buying power are computed. It intentionally includes realized P&L because past profits expand the sizing budget.

---

## What "Account Value" Means on the Dashboard

Source: `dashboard/templates/index.html` → `updateAccountValue()` and `renderState()`

```javascript
// Account Value = balance + open P&L
// balance = get_capital() = deposits + closed_pnl (closed_pnl already included)
$('av').textContent = dollar((acct.balance||0) + (acct.open_pnl||0));
```

Where `acct.balance` comes from `_build_state()` in `dashboard/api.py`:

```python
'balance': round(STARTING_CAPITAL, 2),  # = get_capital()
```

So:

```
Account Value = get_capital() + open_pnl_total
             = (deposits + closed_pnl) + open_pnl
```

- **Balance component:** Same as Capital (= get_capital())
- **Open P&L component:** Unrealized mark-to-market gain/loss on all currently open positions, computed using live Kalshi prices from price_cache

---

## Why They Differ

The gap between "Capital" ($11,294.41) and "Account Value" ($9,724.92) = **−$1,569.49**

This means open positions are showing **$1,569.49 in unrealized losses** at the time of the 3pm scan.

The notification shows `Capital` = the deployment budget (what we have to work with).
The dashboard shows `Account Value` = the true mark-to-market portfolio value (if we closed everything now).

---

## Summary Table

| Concept | Formula | Shown In | Purpose |
|---|---|---|---|
| **Capital** | deposits + realized P&L | Telegram notification | Sizing budget; daily cap denominator |
| **Account Value** | Capital + open P&L | Dashboard header | True current portfolio value |
| **Buying Power** | Capital − deployed open positions | Both | Available to deploy now |

---

## Correct Architecture

This split is **intentional and correct**:

1. Capital is used as the sizing denominator because it represents realized value that is "banked." Open P&L is not banked — it can disappear.
2. Account Value includes open P&L for informational display — it shows the full picture.
3. Using Capital (not Account Value) for cap calculations is conservative: it prevents the bot from sizing up based on paper gains.

---

## No Bug

No code change required. The definitions are clearly distinct and correctly implemented. The notification should say "Capital (Sizing Budget)" and the dashboard "Account Value (Mark-to-Market)" to avoid confusion, but that is a UX clarification, not a bug fix.

**Recommendation:** Add a tooltip or label suffix to the dashboard Account Value and notification Capital line to make the distinction explicit. Not urgent.
