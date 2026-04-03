# Spec: Add `asset=` kwarg to `get_daily_exposure()` + Fix `datetime.utcnow()` in `crypto_1d.py`

**Date:** 2026-03-30  
**Author:** Data Scientist  
**Files:**
- Fix 2: `agents/ruppert/data_scientist/logger.py`
- Fix 3: `agents/ruppert/trader/crypto_1d.py`
**Status:** Ready for Dev

---

## Fix 2: `asset=` kwarg on `get_daily_exposure()`

### Background

`get_daily_exposure(module=None)` currently filters by module only. The `crypto_1d` module needs to query exposure for a specific asset (e.g. BTC) within its module family — for instance, to enforce per-asset position limits without double-counting ETH exposure when checking BTC headroom.

The function already handles multi-day positions correctly by scanning all trade files from `START_DATE` forward and tracking exit keys. The `asset=` filter simply adds an additional condition in the inner loop.

---

### BEFORE

```python
# agents/ruppert/data_scientist/logger.py  (line 226)

def get_daily_exposure(module: str = None) -> float:
    """Calculate total $ exposure from all open positions (any age).

    Reads all trade files from START_DATE forward - the same window used by
    data_agent.get_open_positions_from_logs() - so multi-day positions entered
    2+ days ago are correctly counted. Only sums entries (buys) that have no
    corresponding exit/settle record.
    """
    START_DATE = '2026-03-26'  # bot launch date; matches _get_trade_files() default

    entries   = {}   # key: (ticker, side)  accumulated size_dollars
    exit_keys = set()

    for fname in sorted(os.listdir(TRADES_DIR)):
        if not fname.startswith('trades_') or not fname.endswith('.jsonl'):
            continue
        try:
            file_date = fname[len('trades_'):-len('.jsonl')]
            if file_date < START_DATE:
                continue
        except Exception:
            continue
        log_path = os.path.join(TRADES_DIR, fname)
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ticker = entry.get('ticker', '')
                    side   = entry.get('side', '')
                    action = entry.get('action', 'buy')
                    key    = (ticker, side)
                    if action in ('exit', 'settle'):
                        exit_keys.add(key)
                        entries.pop(key, None)
                    else:
                        if module is not None:
                            entry_module = entry.get('module', '')
                            if not (entry_module == module or
                                    entry_module.startswith(module + '_')):
                                continue
                        # Skip tickers whose settlement time has already passed
                        try:
                            from agents.ruppert.data_scientist.ticker_utils import is_settled_ticker as _is_settled
                            if _is_settled(ticker):
                                continue
                        except Exception:
                            pass
                        entries[key] = entries.get(key, 0) + entry.get('size_dollars', 0)
                except Exception:
                    pass

    return sum(size for key, size in entries.items() if key not in exit_keys)
```

---

### AFTER

Change the signature and add the `asset` filter inside the `else` branch, after the `module` filter and before the settled-ticker check:

```python
def get_daily_exposure(module: str = None, asset: str = None) -> float:
    """Calculate total $ exposure from all open positions (any age).

    Reads all trade files from START_DATE forward - the same window used by
    data_agent.get_open_positions_from_logs() - so multi-day positions entered
    2+ days ago are correctly counted. Only sums entries (buys) that have no
    corresponding exit/settle record.

    Args:
        module: If provided, only sum exposure for positions whose module field
                equals this value OR starts with '{module}_' (e.g. 'crypto' matches
                'crypto' and 'crypto_15m', 'crypto_long').
        asset:  If provided (e.g. 'BTC'), only sum exposure for positions whose
                ticker contains this string (case-insensitive). Applied IN ADDITION
                to the module filter — both conditions must match when both are given.

    No existing callers break: both kwargs default to None.
    """
    START_DATE = '2026-03-26'  # bot launch date; matches _get_trade_files() default

    entries   = {}   # key: (ticker, side)  accumulated size_dollars
    exit_keys = set()

    for fname in sorted(os.listdir(TRADES_DIR)):
        if not fname.startswith('trades_') or not fname.endswith('.jsonl'):
            continue
        try:
            file_date = fname[len('trades_'):-len('.jsonl')]
            if file_date < START_DATE:
                continue
        except Exception:
            continue
        log_path = os.path.join(TRADES_DIR, fname)
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ticker = entry.get('ticker', '')
                    side   = entry.get('side', '')
                    action = entry.get('action', 'buy')
                    key    = (ticker, side)
                    if action in ('exit', 'settle'):
                        exit_keys.add(key)
                        entries.pop(key, None)
                    else:
                        if module is not None:
                            entry_module = entry.get('module', '')
                            if not (entry_module == module or
                                    entry_module.startswith(module + '_')):
                                continue
                        # --- NEW: asset filter ---
                        if asset is not None:
                            if asset.upper() not in ticker.upper():
                                continue
                        # Skip tickers whose settlement time has already passed
                        try:
                            from agents.ruppert.data_scientist.ticker_utils import is_settled_ticker as _is_settled
                            if _is_settled(ticker):
                                continue
                        except Exception:
                            pass
                        entries[key] = entries.get(key, 0) + entry.get('size_dollars', 0)
                except Exception:
                    pass

    return sum(size for key, size in entries.items() if key not in exit_keys)
```

**Change summary:** 4 lines changed / added:
1. Signature: `def get_daily_exposure(module: str = None, asset: str = None) -> float:`
2. Docstring updated to document `asset=` kwarg
3. New 3-line block inserted after module filter:
   ```python
   if asset is not None:
       if asset.upper() not in ticker.upper():
           continue
   ```

---

### Callers

No existing callers pass `asset=`. All existing call sites continue to work unchanged because `asset` defaults to `None` (no-op).

---

### Edge Cases

| Case | Expected behaviour |
|------|--------------------|
| `get_daily_exposure()` | Unchanged — returns total exposure across all positions |
| `get_daily_exposure(module='crypto_long')` | Unchanged — returns crypto_long exposure |
| `get_daily_exposure(asset='BTC')` | Only BTC-ticker exposure, all modules |
| `get_daily_exposure(module='crypto_long', asset='BTC')` | BTC exposure within crypto_long only |
| `asset='btc'` (lowercase) | Case-insensitive — still matches KXBTC tickers |

---

### Testing Checklist (for QA)

- [ ] `get_daily_exposure()` returns same value as before (no args, regression)
- [ ] `get_daily_exposure(module='crypto_long')` returns same value as before
- [ ] `get_daily_exposure(asset='BTC')` returns sum only for BTC-ticker positions
- [ ] `get_daily_exposure(module='crypto_long', asset='BTC')` returns intersection
- [ ] Exited BTC positions are correctly excluded
- [ ] Case-insensitive: `asset='btc'` matches `KXBTC` tickers

---

---

## Fix 3: Replace `datetime.utcnow()` in `crypto_1d.py`

**File:** `agents/ruppert/trader/crypto_1d.py`  
**Line:** 995

`datetime.utcnow()` is deprecated as of Python 3.12 and will be removed in a future version. The rest of `crypto_1d.py` uses `datetime.now(timezone.utc)` consistently. This one stray call should be aligned.

### BEFORE

```python
# crypto_1d.py, line 995
'timestamp': datetime.utcnow().isoformat() + 'Z',
```

### AFTER

```python
# crypto_1d.py, line 995
'timestamp': datetime.now(timezone.utc).isoformat(),
```

**Notes:**
- `datetime.now(timezone.utc).isoformat()` already produces a timezone-aware ISO string ending in `+00:00` (e.g. `2026-03-30T17:00:00+00:00`), which is unambiguous and RFC 3339 compliant. The trailing `'Z'` suffix is no longer needed.
- `timezone` is already imported at the top of `crypto_1d.py` (confirmed by usage elsewhere in the file).
- This is a one-line change. No logic impact; purely a deprecation fix.

### Testing Checklist (for QA)

- [ ] `crypto_1d.py` produces no `DeprecationWarning` for `utcnow` after fix
- [ ] `timestamp` field in trade log records is a valid ISO 8601 datetime string with UTC offset
