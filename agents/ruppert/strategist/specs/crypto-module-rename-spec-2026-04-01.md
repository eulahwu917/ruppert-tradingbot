# Spec: Crypto Module Rename & Band Extraction

**Author:** Strategist (Opus)
**Date:** 2026-04-01
**Type:** Structural refactor — zero logic changes
**Priority:** P1 (taxonomy hygiene, blocks correct per-asset reporting)

---

## Motivation

The taxonomy principle is: **every file should match its module name**.

Right now we have two violations:

1. `crypto_1d.py` contains threshold logic but is named after the old umbrella module `crypto_1d`, not the taxonomy name `crypto_threshold_daily_*`.
2. Band logic (`crypto_band_daily_*`) lives inside `main.py` instead of its own file.
3. SOL/XRP/DOGE band trades are misclassified as `crypto_band_daily_btc` due to incomplete TODO stubs at `main.py:578-586`.

This spec fixes all three. **No logic changes.** Move code, rename files, update references.

---

## Part 1: Rename `crypto_1d.py` -> `crypto_threshold_daily.py`

### File operation
```
agents/ruppert/trader/crypto_1d.py  ->  agents/ruppert/trader/crypto_threshold_daily.py
```

No internal logic changes. Update the docstring header from `crypto_1d.py` to `crypto_threshold_daily.py` and the "Run via" comment from `ruppert_cycle.py crypto_1d` to `ruppert_cycle.py crypto_1d` (the CLI mode name stays `crypto_1d` for backwards compat — only the file/import path changes).

### Import updates (4 files)

| File | Line | Old | New |
|------|------|-----|-----|
| `agents/ruppert/trader/main.py` | 779 | `from agents.ruppert.trader.crypto_1d import evaluate_crypto_1d_entry, ASSETS_PHASE1` | `from agents.ruppert.trader.crypto_threshold_daily import evaluate_crypto_1d_entry, ASSETS_PHASE1` |

That is the **only direct import** of `crypto_1d` as a module path. The `ruppert_cycle.py` import at line 750 imports from `main.py`, not from `crypto_1d.py` directly, so it does not need a path change.

### String-literal references to update (keep or change?)

These are **string identifiers**, not import paths. Most should stay as-is because they refer to the CLI mode name or source tag, not the file:

| File | Line(s) | String | Action |
|------|---------|--------|--------|
| `agents/ruppert/trader/crypto_1d.py` (now `crypto_threshold_daily.py`) | 1048 | `'source': 'crypto_1d'` | **Keep** — this is the trade source tag consumed by `classify_module()` in logger.py. Changing it would break classification. |
| `agents/ruppert/data_scientist/logger.py` | 514-521 | `src == 'crypto_1d'` | **Keep** — matches the source tag above. |
| `agents/ruppert/trader/position_tracker.py` | 419, 426 | `'crypto_1d'` in log strings | **Keep** — cosmetic log text, low risk. Can clean up later. |
| `environments/demo/ruppert_cycle.py` | 741-801, 1254-1274 | `'crypto_1d'` mode string | **Keep** — this is the CLI mode name. Renaming it would break Task Scheduler XML args. |
| `environments/demo/config.py` | 233-245 | `CRYPTO_1D_*` config keys | **Keep** — renaming config keys is a separate spec (high blast radius). |
| `environments/demo/scripts/migrate_module_taxonomy.py` | 82-83 | `'crypto_1d'` | **Keep** — migration script references old names by design. |

### Summary: Part 1 touches

- **1 file rename:** `crypto_1d.py` -> `crypto_threshold_daily.py`
- **1 import update:** `main.py:779`
- **1 docstring update:** in the renamed file itself (line 2)

---

## Part 2: Extract band logic from `main.py` -> `crypto_band_daily.py`

### New file
```
agents/ruppert/trader/crypto_band_daily.py
```

### What to extract from `main.py`

Move these into `crypto_band_daily.py`:

| main.py lines | What | Notes |
|---------------|------|-------|
| 427-439 | `band_prob()` helper function | Log-normal band probability calculator. Uses `math`, `scipy.stats.norm`. |
| 444-760 | `run_crypto_scan()` function | The entire band scanning + execution function. This is the core band logic. |

### What stays in `main.py`

- The `run_crypto_1d_scan()` function (lines 765-860+) stays — it's the threshold wrapper.
- All non-band code stays.
- Replace the extracted functions with imports from the new file.

### New file structure: `crypto_band_daily.py`

```python
"""
crypto_band_daily.py -- Daily crypto band (above/below range) trading module.

Trades KXBTC / KXETH / KXSOL / KXXRP / KXDOGE band markets on Kalshi.
Formerly embedded in main.py as run_crypto_scan().
"""

# Move all imports needed by band_prob() and run_crypto_scan() here.
# Keep the same internal logic — zero changes.

def band_prob(spot, band_mid, half_w, sigma, drift=0.0):
    ...  # exact copy from main.py:427-439

def run_crypto_scan(dry_run=True, direction='neutral', traded_tickers=None, open_position_value=0.0):
    ...  # exact copy from main.py:444-760
```

### Import updates after extraction

| File | Line | Old | New |
|------|------|-----|-----|
| `agents/ruppert/trader/main.py` | (was inline) | Direct `run_crypto_scan()` definition | `from agents.ruppert.trader.crypto_band_daily import run_crypto_scan` |

Any callers of `run_crypto_scan` that import from `main.py` will still work because `main.py` re-exports it. But check for direct callers:

| File | Reference | Action |
|------|-----------|--------|
| `environments/demo/ruppert_cycle.py` | Imports `run_crypto_scan` from `agents.ruppert.trader.main` (grep to confirm exact line) | **No change needed** if main.py re-exports. Otherwise update import. |

### Imports the new file needs (move from main.py)

The extracted function uses these imports internally (some are inline `from ... import` inside the function body — keep those inline):
- `math` (for `band_prob`)
- `scipy.stats.norm` (imported inside `band_prob`)
- `datetime`, `timezone` from `datetime`
- `config` (already on sys.path)
- `from agents.ruppert.strategist.strategy import should_enter, check_daily_cap, check_open_exposure`
- `from agents.ruppert.data_scientist.capital import get_capital, get_buying_power`
- `from agents.ruppert.data_scientist.logger import log_activity`
- Inline imports inside `run_crypto_scan()`: keep as-is (they're deferred for a reason)

---

## Part 3: Fix TODO taxonomy bugs (SOL/XRP/DOGE band module names)

### Location: `main.py:578-586` (will move to `crypto_band_daily.py` as part of Part 2)

### Current (broken)
```python
_SERIES_TO_BAND_MODULE = {
    'KXBTC':  'crypto_band_daily_btc',
    'KXETH':  'crypto_band_daily_eth',
    'KXSOL':  'crypto_band_daily_btc',   # TODO: verify taxonomy
    'KXXRP':  'crypto_band_daily_btc',   # TODO: verify taxonomy
    'KXDOGE': 'crypto_band_daily_btc',   # TODO: verify taxonomy
}
_band_module = _SERIES_TO_BAND_MODULE.get(series, 'crypto_band_daily_btc')  # TODO: verify taxonomy
```

### Fixed
```python
_SERIES_TO_BAND_MODULE = {
    'KXBTC':  'crypto_band_daily_btc',
    'KXETH':  'crypto_band_daily_eth',
    'KXSOL':  'crypto_band_daily_sol',
    'KXXRP':  'crypto_band_daily_xrp',
    'KXDOGE': 'crypto_band_daily_doge',
}
_band_module = _SERIES_TO_BAND_MODULE.get(series, 'crypto_band_daily_btc')
```

### Downstream impact

These module names flow into `logger.log_trade()` and `classify_module()`. Verify that `classify_module()` in `logger.py` handles `crypto_band_daily_sol`, `crypto_band_daily_xrp`, `crypto_band_daily_doge` correctly. The current classifier (logger.py:526-536) should already handle these via the `crypto_band_daily_` prefix pattern — confirm before merging.

### Also update the daily cap sum (currently only BTC+ETH)

In `run_crypto_scan()` (main.py:621-625, moving to `crypto_band_daily.py`):

**Current:**
```python
_crypto_deployed_this_cycle = sum(
    _get_daily_exp(module=m)
    for m in ('crypto_band_daily_btc', 'crypto_band_daily_eth')
)
```

**Fixed:**
```python
_crypto_deployed_this_cycle = sum(
    _get_daily_exp(module=m)
    for m in ('crypto_band_daily_btc', 'crypto_band_daily_eth',
              'crypto_band_daily_sol', 'crypto_band_daily_xrp',
              'crypto_band_daily_doge')
)
```

---

## Part 4: Update `ruppert_cycle.py` and other importers

### `environments/demo/ruppert_cycle.py`

No import changes needed — it imports `run_crypto_scan` and `run_crypto_1d_scan` from `agents.ruppert.trader.main`, and main.py will re-export `run_crypto_scan` from the new `crypto_band_daily.py`. Verify the import chain works.

The CLI mode name `crypto_1d` stays unchanged (it's an interface, not a file name).

### Other files — verify no direct imports of `run_crypto_scan` from `main`

Grep for `from agents.ruppert.trader.main import run_crypto_scan` across the codebase. If any exist beyond `ruppert_cycle.py`, update them.

---

## Part 5: Task Scheduler name update

### File: `scripts/setup/Ruppert-Crypto1D.xml`

**Current (line 7):**
```xml
<Description>Ruppert crypto_1d scanner: daily crypto above/below (KXBTCD/KXETHD/KXSOLD). Runs 06:30 AM + 10:30 AM PDT.</Description>
```

**Updated:**
```xml
<Description>Ruppert crypto_threshold_daily scanner: daily crypto above/below (KXBTCD/KXETHD/KXSOLD). Runs 06:30 AM + 10:30 AM PDT.</Description>
```

**Current (line 9):**
```xml
<URI>\Ruppert-Crypto1D</URI>
```

**Updated:**
```xml
<URI>\Ruppert-CryptoThresholdDaily</URI>
```

**Note:** The command-line argument (`-m environments.demo.ruppert_cycle crypto_1d`) stays the same — the CLI mode name is unchanged.

### File: `environments/demo/scripts/setup/setup_crypto_1d_scheduler.ps1`

Update the task name reference and description to match the XML changes. The script filename itself can be renamed to `setup_crypto_threshold_daily_scheduler.ps1` for consistency.

---

## Execution order

1. **Create** `agents/ruppert/trader/crypto_band_daily.py` (extract from main.py)
2. **Fix** the TODO taxonomy mapping in the extracted code (Part 3)
3. **Update** main.py: remove extracted code, add import from `crypto_band_daily`
4. **Rename** `crypto_1d.py` -> `crypto_threshold_daily.py`
5. **Update** main.py:779 import path
6. **Update** Task Scheduler XML + PowerShell setup script (Part 5)
7. **Test:** `python -m environments.demo.ruppert_cycle crypto_1d` still works (dry run)
8. **Test:** `python -c "from agents.ruppert.trader.crypto_band_daily import run_crypto_scan"` imports cleanly
9. **Test:** `python -c "from agents.ruppert.trader.crypto_threshold_daily import evaluate_crypto_1d_entry"` imports cleanly

---

## Files changed (complete list)

| # | File | Change type |
|---|------|-------------|
| 1 | `agents/ruppert/trader/crypto_1d.py` | **Rename** -> `crypto_threshold_daily.py` + update docstring |
| 2 | `agents/ruppert/trader/crypto_band_daily.py` | **New file** — `band_prob()` + `run_crypto_scan()` extracted from main.py |
| 3 | `agents/ruppert/trader/main.py` | **Edit** — remove extracted band logic, add import from `crypto_band_daily`, update `crypto_1d` import path to `crypto_threshold_daily` |
| 4 | `scripts/setup/Ruppert-Crypto1D.xml` | **Edit** — update Description + URI |
| 5 | `environments/demo/scripts/setup/setup_crypto_1d_scheduler.ps1` | **Rename** -> `setup_crypto_threshold_daily_scheduler.ps1` + update contents |

## Files NOT changed (and why)

| File | Why unchanged |
|------|---------------|
| `environments/demo/ruppert_cycle.py` | Imports from `main.py` which re-exports — no path change needed |
| `environments/demo/config.py` | `CRYPTO_1D_*` config keys stay — renaming config keys is a separate spec |
| `agents/ruppert/data_scientist/logger.py` | `src == 'crypto_1d'` matches the source tag, not the file — no change |
| `agents/ruppert/trader/position_tracker.py` | Log strings only — cosmetic, separate cleanup |
| `environments/demo/scripts/migrate_module_taxonomy.py` | References old names by design |

---

## Risk assessment

- **Low risk.** Pure structural refactor. No logic changes, no config key renames, no CLI mode changes.
- **Rollback:** git revert single commit.
- **Verify:** three import smoke tests (listed in execution order step 7-9).
