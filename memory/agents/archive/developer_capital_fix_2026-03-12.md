# Developer Summary — Capital Fix
_SA-3 Developer | 2026-03-12_

## Task
Fix stale capital reading. Bot was logging `Capital: $172.37` but true buying power is ~$510.

## Root Cause
`client.get_balance()` queries the Kalshi demo API and returns a stale cached/API balance (~$172).
This was being used as `total_capital` in:
- `main.py` `run_weather_scan()` (the `[Weather] Capital:` log line)
- `ruppert_cycle.py` crypto daily cap check

## Fix Applied

### `logger.py` — new function `get_computed_capital()`
Computes true capital from first principles:
1. Sums `amount` from all records in `logs/demo_deposits.jsonl`
2. Sums `realized_pnl` from all `action == "exit"` records across all `logs/trades_*.jsonl` files

### `main.py`
- Added `get_computed_capital` to import from `logger`
- Changed `total_capital = client.get_balance()` → `total_capital = get_computed_capital()`

### `ruppert_cycle.py`
- Added `get_computed_capital` to import from `logger`
- Changed `_total_capital = client.get_balance()` → `_total_capital = get_computed_capital()`

## Verified Output
```
python -c "from logger import get_computed_capital; print('Capital:', get_computed_capital())"
Capital: 510.3
```
- Deposits: $400 (2 × $200 from `demo_deposits.jsonl`)
- Realized P&L: $110.30 (from 11 exit records in `trades_2026-03-11.jsonl`)
- **Total computed capital: $510.30**

The 70% daily cap (`Remaining`) will now correctly show ~$357 (70% of $510).

## Git Commit
`01c687a` — `fix: use computed capital (deposits + realized P&L) instead of stale get_balance()`

Files changed: `logger.py`, `main.py`, `ruppert_cycle.py` (54 insertions, 4 deletions)

## Notes for QA / CEO
- `client.get_balance()` still exists and is called in other non-capital-sizing contexts
  (`check_balance.py`, `kalshi_client.py` test block, `dashboard/api.py`, `trader.py`).
  Those are not part of this fix scope — they don't drive trade sizing decisions.
- `dashboard/api.py` uses `get_balance()` for the dashboard balance display —
  flagging as a follow-up: dashboard should also show computed capital for consistency.
- No trading thresholds were changed.
- No secrets/ files touched.
