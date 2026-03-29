# TRADER SPECS — Round 2

---

## TR2-1 — crypto_15m: add_position() missing module and title

**ID:** T-R2-1
**Severity:** MEDIUM
**File:** `agents/ruppert/trader/crypto_15m.py`
**Function:** `evaluate_crypto_15m_entry()`

### Problem

The `position_tracker.add_position()` call does not pass `module` or `title`. The position tracker stores these for downstream display and filtering. Without them, 15m positions appear with blank module/title in monitoring, and `get_daily_exposure(module='crypto_15m')` cannot match them.

### Current Code (lines near end of execute block)

```python
position_tracker.add_position(ticker, fill_contracts_pt, direction, fill_price_pt)
```

### Required Change

```python
position_tracker.add_position(
    ticker,
    fill_contracts_pt,
    direction,
    fill_price_pt,
    module='crypto_15m',
    title=f'{asset} 15m direction',
)
```

`asset` is already in scope at this point (parsed earlier by `_parse_asset_from_ticker(ticker)`).

### Acceptance Criteria

- `position_tracker.add_position()` is called with exactly those five keyword arguments.
- No other call sites to `position_tracker.add_position` are modified.
- `asset` variable is confirmed in scope at the call site (it is — defined at top of `evaluate_crypto_15m_entry`).

---

## TR2-2 — post_trade_monitor: check_settlements() dead logs_dir parameter

**ID:** T-R2-2
**Severity:** LOW
**File:** `agents/ruppert/trader/post_trade_monitor.py`
**Function:** `check_settlements()` and its call site in `run_monitor()`

### Problem

`check_settlements(client, logs_dir: Path)` accepts `logs_dir` but ignores it. All paths inside the function use the module-level constant `TRADES_DIR`. The dead parameter misleads readers into thinking it controls where trades are read/written.

Additionally, any caller in `position_monitor.py` that passes `logs_dir` must be updated.

### Current Signature

```python
def check_settlements(client, logs_dir: Path):
```

### Current Call Site in run_monitor()

```python
check_settlements(client, TRADES_DIR)
```

### Required Changes

**1. Remove parameter from signature:**

```python
def check_settlements(client):
```

**2. Update call site in `run_monitor()`:**

```python
check_settlements(client)
```

**3. Audit `position_monitor.py`:**

Search for any call matching `check_settlements(` in `agents/ruppert/trader/position_monitor.py`. If found, remove the `logs_dir` argument from that call too. If the file does not call `check_settlements`, no change needed there.

### Acceptance Criteria

- `check_settlements` signature has exactly one parameter: `client`.
- All call sites (at minimum `run_monitor()` in `post_trade_monitor.py`) pass only `client`.
- `TRADES_DIR` (module-level constant) continues to be used inside the function body — no path logic changes.
- No other behavior changes.

---

## TR2-3 — main.py: _load_trade_record() globs wrong directory

**ID:** T-R2-3
**Severity:** LOW
**File:** `agents/ruppert/trader/main.py`
**Function:** `_load_trade_record()`

### Problem

The function builds a glob pattern using `_LOGS_DIR` (the flat `logs/` directory), but trade files live in `_TRADES_DIR` (i.e., `logs/trades/`). No trades will ever be found, so exit-scan logic always falls back to default `entry_price=50` and `entry_edge=0.0`.

### Current Code

```python
_LOGS_DIR = str(_env_paths['logs'])

def _load_trade_record(ticker: str) -> dict | None:
    import glob
    pattern = os.path.join(_LOGS_DIR, 'trades_*.jsonl')
    ...
```

### Required Changes

**1. Add `_TRADES_DIR` constant** (after the existing `_LOGS_DIR` line):

```python
_LOGS_DIR   = str(_env_paths['logs'])
_TRADES_DIR = str(_env_paths['trades'])
```

**2. Update the glob pattern inside `_load_trade_record()`:**

```python
pattern = os.path.join(_TRADES_DIR, 'trades_*.jsonl')
```

No other logic in the function changes.

### Acceptance Criteria

- `_TRADES_DIR` is defined as `str(_env_paths['trades'])` at module level.
- `_load_trade_record()` uses `_TRADES_DIR` in its glob pattern.
- `_LOGS_DIR` is unchanged and still used for `_STRATEGY_EXITS_LOG`.
- A manual test with a known ticker that has an existing trade record in `logs/trades/` returns the correct dict (not `None`).

---

## TR2-4 — logger.py: get_daily_exposure() overly broad module filter

**ID:** T-R2-4
**Severity:** LOW
**File:** `agents/ruppert/data_scientist/logger.py`
**Function:** `get_daily_exposure()`

### Problem

The module filter has three conditions:

```python
if not (entry_module == module or
        entry_module.startswith(module + '_') or
        entry_module.startswith(module)):
```

The third condition (`entry_module.startswith(module)`) subsumes both the first (`==`) and second (`startswith(module + '_')`), making them dead code. Worse, it causes false positives: e.g., `module='crypto'` would match `entry_module='crypto_15m'` AND `entry_module='crypto_client'` or any other string starting with `crypto`. The intent is to match exact module name or sub-module variants (e.g., `crypto_15m`), not arbitrary prefix matches.

### Current Code

```python
if not (entry_module == module or
        entry_module.startswith(module + '_') or
        entry_module.startswith(module)):
    continue
```

### Required Change

Remove the third condition. Keep only exact match and underscore-delimited sub-module match:

```python
if not (entry_module == module or
        entry_module.startswith(module + '_')):
    continue
```

### Acceptance Criteria

- The filter has exactly two conditions: `entry_module == module` and `entry_module.startswith(module + '_')`.
- The third condition `entry_module.startswith(module)` is removed entirely.
- `get_daily_exposure(module='crypto')` matches `crypto` and `crypto_15m` but NOT `crypto_client` or other incidental prefix matches.
- `get_daily_exposure(module=None)` path (no filtering) is unchanged.
- No other changes to the function.
