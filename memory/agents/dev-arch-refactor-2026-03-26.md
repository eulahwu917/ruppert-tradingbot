# Architectural Refactor: Crypto + Fed → main.py
**Date:** 2026-03-26  
**Agent:** SA-3 Developer (subagent)  
**Status:** ✅ Complete — both files pass AST syntax check

## What Changed

### `main.py` (additions)
1. **New imports** added at top:
   - `import math`
   - `import requests`
   - `from datetime import date, datetime` (was only `datetime`)
   - `log_trade` added to logger import

2. **`band_prob(spot, band_mid, half_w, sigma, drift=0.0)`** — log-normal band probability helper, placed in new `# ─── CRYPTO / FED HELPERS` section before economics module.

3. **`run_crypto_scan(dry_run=True, direction='neutral', traded_tickers=None, open_position_value=0.0)`**
   - Extracted from `ruppert_cycle.py` STEP 4 (was ~150 lines inline)
   - Instantiates its own `KalshiClient()`
   - Uses `dry_run` param (not `config.DRY_RUN`)
   - Returns list of executed opp dicts
   - Logs with `[AUTO-CRYPTO]` prefix

4. **`run_fed_scan(dry_run=True, traded_tickers=None, open_position_value=0.0)`**
   - Extracted from `ruppert_cycle.py` STEP 4b (was ~80 lines inline)
   - Imports `fed_client.run_fed_scan` as `_run_fed_scan_inner` to avoid name collision
   - Instantiates its own `KalshiClient()`
   - Returns list of executed opp dicts

### `ruppert_cycle.py` (changes)
1. **STEP 4** (lines 348–541, ~194 lines) → replaced with 16-line delegating block:
   ```python
   from main import run_crypto_scan
   new_crypto = run_crypto_scan(dry_run=DRY_RUN, direction=direction, ...)
   ```

2. **STEP 4b** (lines 542–673, ~132 lines) → replaced with 14-line delegating block:
   ```python
   from main import run_fed_scan as _run_fed_scan_cycle
   new_fed = _run_fed_scan_cycle(dry_run=DRY_RUN, ...)
   ```

3. **Summary section** updated:
   - `'crypto_trades': _crypto_trades_executed if '_crypto_trades_executed' in dir() else 0`
   - → `'crypto_trades': len(new_crypto) if new_crypto else 0`

4. `_c_opps` in scan notification already used `len(new_crypto)` — no change needed.

## Line Count
- `ruppert_cycle.py`: 765 → 469 lines (296 lines removed)
- `main.py`: 518 → ~820 lines (added ~300 lines of new functions)

## Architecture Pattern
All three trade modules now follow the same pattern in `ruppert_cycle.py`:
```python
from main import run_<module>_scan
new_<module> = run_<module>_scan(dry_run=DRY_RUN, ...)
```

## Tests
- `python -c "import ast; ast.parse(open('main.py', ...).read())"` → **OK**
- `python -c "import ast; ast.parse(open('ruppert_cycle.py', ...).read())"` → **OK**
- Custom verification script: all 8 assertions passed
