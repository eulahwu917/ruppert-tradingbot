---
name: Cycle Refactor Plan
description: Technical spec for refactoring ruppert_cycle.py from top-level script to testable module with function-based architecture
type: project
---

# ruppert_cycle.py Refactor — Technical Spec for Developer

**Author:** Architect (Opus)
**Date:** 2026-03-27
**Status:** PLAN — awaiting Dev implementation + QA validation

---

## 1. Current State

`ruppert_cycle.py` is 784 lines. All code runs at module level on import. Key problems:
- Importing the file triggers API calls, file writes, Telegram messages
- No way to unit test individual steps
- Shared mutable state (`traded_tickers`, `OPEN_POSITION_VALUE`, `actions_taken`) via globals
- Mode dispatch via sequential `if MODE == ...: ... sys.exit(0)` blocks

### Current Flow (in execution order)

1. **Module-level setup** (L1-31): imports, MODE from argv, LOGS path, DRY_RUN
2. **Utility functions** (L33-88): `ts()`, `push_alert()`, `log_cycle()`, `save_state()`, `run_post_cycle_exposure_check()`
3. **Banner + log rotation** (L92-101)
4. **Client init** (L103): `KalshiClient()`
5. **Load traded_tickers from trade log** (L106-126)
6. **Merge traded_tickers from state.json** (L128-144)
7. **Loss circuit breaker** (L146-159)
8. **Compute open exposure** (L161-167)
9. **Orphan reconciliation** (L169-205)
10. **Exposure reconciliation** (L207-221)
11. **Position check** (L223-332) — runs for ALL modes
12. **Mode: check** (L334-338) — exit early
13. **Mode: econ_prescan** (L341-452) — exit early
14. **Mode: weather_only** (L455-473) — exit early
15. **Mode: crypto_only** (L476-494) — exit early
16. **Mode: report** (L497-605) — exit early
17. **Full/smart mode continues:**
    - Step 1b: Wallet list refresh (L607-615)
    - Step 2: Smart money refresh (L617-637)
    - Step 3: Weather scan (L639-655)
    - Step 4: Crypto scan (L657-674)
    - Step 4b: Fed scan (L676-688)
    - Step 5: Security audit — Sunday only (L690-704)
    - Summary + notification (L706-784)

---

## 2. Target Architecture

### 2.1 File Structure

**Single file refactor** — keep everything in `ruppert_cycle.py`. No new files. This minimizes blast radius and avoids import chain changes.

### 2.2 Data Containers

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class CycleState:
    """Mutable state bag passed through the cycle."""
    mode: str
    dry_run: bool
    logs_dir: Path
    traded_tickers: set = field(default_factory=set)
    open_position_value: float = 0.0
    actions_taken: list = field(default_factory=list)
    capital: float = 0.0
    buying_power: float = 0.0
    direction: str = 'neutral'  # smart money direction (full mode)
```

### 2.3 Function Signatures — Complete List

All functions below are module-level, defined in `ruppert_cycle.py`.

#### Utility functions (KEEP AS-IS — already functions)

```python
def ts() -> str: ...                                     # L33-34  — no change
def push_alert(level: str, message: str,                 # L36-47  — no change
               ticker: str = None, pnl: float = None) -> None: ...
def log_cycle(mode: str, event: str, data: dict = None) -> None: ...  # L49-53 — add mode param
def run_post_cycle_exposure_check() -> None: ...         # L70-88  — no change
```

**Change to `log_cycle`:** Add `mode` as first param instead of reading global `MODE`. Signature becomes `log_cycle(mode, event, data=None)`.

**Change to `save_state`:** Currently reads globals. New signature:

```python
def save_state(logs_dir: Path, traded_tickers: set, mode: str) -> None:
    """Write traded_tickers + metadata to logs/state.json."""
```

#### Init / Setup functions (NEW)

```python
def load_traded_tickers(logs_dir: Path) -> set:
    """Load traded tickers from today's trade log + state.json.

    Returns set of ticker strings that have been traded today.
    Merges from both trades_YYYY-MM-DD.jsonl and state.json (if same-day).
    """

def check_circuit_breaker(logs_dir: Path, capital: float) -> Optional[dict]:
    """Run loss circuit breaker check.

    Returns None if OK, or dict with 'tripped', 'reason', 'loss_today' if tripped.
    Prints status to stdout.
    """

def compute_open_exposure(capital: float, buying_power: float) -> float:
    """Compute open position value from capital - buying_power.

    Returns max(0.0, capital - buying_power).
    """
```

#### Reconciliation functions (NEW)

```python
def run_orphan_reconciliation(client: 'KalshiClient', logs_dir: Path) -> None:
    """Compare Kalshi positions against trade log. Push alerts for orphans.

    Prints reconciliation summary. Non-blocking on errors.
    """

def run_exposure_reconciliation(
    logs_dir: Path, capital: float, buying_power: float
) -> None:
    """Compare log-based exposure vs API-based exposure.

    Pushes alert if divergence > $50 and > 5%. Non-blocking on errors.
    """
```

#### Position Check (NEW)

```python
def run_position_check(
    client: 'KalshiClient',
    state: CycleState,
) -> list:
    """Check all open positions, trigger weather alerts, execute auto-exits.

    Mutates state.traded_tickers (adds auto-exited tickers).
    Returns list of (action, ticker, side, price, contracts, pnl) tuples for actions taken.
    """
```

#### Mode-specific handlers (NEW)

Each returns a summary dict suitable for `log_cycle`.

```python
def run_check_mode(state: CycleState) -> dict:
    """Check-only mode: just position check, then exit.
    Returns {'actions': int}.
    """

def run_econ_prescan_mode(
    client: 'KalshiClient',
    state: CycleState,
) -> dict:
    """Econ prescan: check releases, trade if any today.
    Returns {'econ_trades': int, 'reason': str (optional)}.
    """

def run_weather_only_mode(state: CycleState) -> dict:
    """Weather-only scan mode.
    Returns {'weather_trades': int}.
    """

def run_crypto_only_mode(state: CycleState) -> dict:
    """Crypto-only scan mode.
    Returns {'crypto_trades': int}.
    """

def run_report_mode(state: CycleState) -> dict:
    """7am P&L summary + loss detection + optimizer review.
    Returns {'exit_count': int, 'losses': int}.
    """

def run_full_mode(
    client: 'KalshiClient',
    state: CycleState,
) -> dict:
    """Full cycle: wallet refresh, smart money, weather, crypto, fed, security audit, notification.
    Returns {'weather_trades': int, 'crypto_trades': int, 'fed_trades': int,
             'smart_money': str, 'auto_exits': int}.
    """
```

#### Top-level orchestrator (NEW)

```python
def run_cycle(mode: str) -> None:
    """Main entry point. Sets up state, runs common init, dispatches to mode handler.

    Steps:
    1. Print banner, rotate logs
    2. Init KalshiClient
    3. Load traded_tickers
    4. Circuit breaker check (exit if tripped)
    5. Compute open exposure
    6. Run orphan + exposure reconciliation
    7. Run position check (all modes)
    8. Dispatch to mode handler
    9. save_state() + log_cycle('done', summary)
    """
```

---

## 3. Detailed Implementation Notes

### 3.1 `run_cycle(mode)` — The Orchestrator

```python
def run_cycle(mode: str) -> None:
    print(f"\n{'='*60}")
    print(f"  RUPPERT CYCLE  mode={mode.upper()}  {ts()}")
    print(f"{'='*60}")
    log_cycle(mode, 'start')

    try:
        rotate_logs()
    except Exception as e:
        print(f"[Logger] Log rotation skipped: {e}")

    client = KalshiClient()
    logs_dir = Path(__file__).parent / 'logs'
    logs_dir.mkdir(exist_ok=True)

    traded_tickers = load_traded_tickers(logs_dir)

    # Circuit breaker
    capital = get_capital()
    cb = check_circuit_breaker(logs_dir, capital)
    if cb and cb.get('tripped'):
        save_state(logs_dir, traded_tickers, mode)
        log_cycle(mode, 'circuit_breaker', cb)
        sys.exit(0)

    buying_power = get_buying_power()
    open_exposure = compute_open_exposure(capital, buying_power)

    state = CycleState(
        mode=mode,
        dry_run=config.DRY_RUN,
        logs_dir=logs_dir,
        traded_tickers=traded_tickers,
        open_position_value=open_exposure,
        capital=capital,
        buying_power=buying_power,
    )

    # Reconciliation (all modes)
    run_orphan_reconciliation(client, logs_dir)
    run_exposure_reconciliation(logs_dir, capital, buying_power)

    # Position check (all modes)
    state.actions_taken = run_position_check(client, state)

    # Dispatch
    if mode == 'check':
        summary = run_check_mode(state)
    elif mode == 'econ_prescan':
        summary = run_econ_prescan_mode(client, state)
    elif mode == 'weather_only':
        summary = run_weather_only_mode(state)
    elif mode == 'crypto_only':
        summary = run_crypto_only_mode(state)
    elif mode == 'report':
        summary = run_report_mode(state)
    elif mode in ('full', 'smart'):
        summary = run_full_mode(client, state)
    else:
        raise ValueError(f'Unknown mode: {mode}')

    save_state(logs_dir, state.traded_tickers, mode)
    log_cycle(mode, 'done', summary)
```

**Key principle:** Each mode handler calls `sys.exit(0)` ONLY if it needs to (for the early-exit modes, this is no longer needed since `run_cycle` handles the flow). However, to preserve backward compatibility during the transition, mode handlers can simply `return` their summary dict.

### 3.2 Moving Code into Functions

Each function is a direct cut-and-paste of the existing code block, with these mechanical changes:

1. Replace `traded_tickers` global → `state.traded_tickers`
2. Replace `OPEN_POSITION_VALUE` global → `state.open_position_value`
3. Replace `DRY_RUN` global → `state.dry_run`
4. Replace `MODE` global → `state.mode`
5. Replace `LOGS` global → `state.logs_dir`
6. Replace `actions_taken` global → `state.actions_taken`
7. `save_state()` calls get explicit params instead of reading globals
8. `log_cycle()` calls get `state.mode` as first param
9. Remove all `sys.exit(0)` from mode handlers — flow returns to `run_cycle`

### 3.3 The `if __name__ == '__main__'` Block

```python
if __name__ == '__main__':
    _mode = sys.argv[1] if len(sys.argv) > 1 else 'full'
    run_cycle(_mode)
```

### 3.4 Module-Level Code After Refactor

The ONLY module-level code should be:
1. Imports
2. `sys.stdout.reconfigure(encoding='utf-8')`
3. Constants: `LOGS`, `ALERTS_FILE`, `ALERT_LOG` (these are path constants, safe)
4. Function definitions
5. `CycleState` dataclass
6. `if __name__ == '__main__':` block

**Critical:** No `KalshiClient()` instantiation, no file reads, no API calls at module level.

---

## 4. Test Updates

### 4.1 Current Tests (tests/test_cycle_modes.py)

All 4 tests do **static text analysis** of `ruppert_cycle.py`. They grep for patterns like `if MODE == 'check'`. After the refactor:

- `if MODE == 'check'` becomes `if mode == 'check'` (inside `run_cycle`)
- The pattern `if\s+MODE\s*==\s*['"]check['"]` will no longer match

### 4.2 Test Migration Plan

**Replace all 4 tests.** The new tests should verify structure, not grep for string patterns.

```python
"""Tests for ruppert_cycle.py module structure and mode dispatch."""
import importlib
import inspect
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_MODES = ['check', 'econ_prescan', 'weather_only', 'crypto_only', 'report']
FALLTHROUGH_MODES = {'full', 'smart'}


def _import_cycle():
    """Import ruppert_cycle without executing the cycle."""
    import importlib
    # This should now be safe — no side effects at module level
    spec = importlib.util.spec_from_file_location(
        'ruppert_cycle', REPO_ROOT / 'ruppert_cycle.py'
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Test 1: run_cycle exists and is callable
def test_run_cycle_exists():
    mod = _import_cycle()
    assert hasattr(mod, 'run_cycle'), "ruppert_cycle.py must export run_cycle()"
    assert callable(mod.run_cycle)


# Test 2: Each required mode has a dedicated handler function
def test_mode_handler_functions_exist():
    mod = _import_cycle()
    expected = {
        'check': 'run_check_mode',
        'econ_prescan': 'run_econ_prescan_mode',
        'weather_only': 'run_weather_only_mode',
        'crypto_only': 'run_crypto_only_mode',
        'report': 'run_report_mode',
    }
    missing = []
    for mode, func_name in expected.items():
        if not hasattr(mod, func_name) or not callable(getattr(mod, func_name)):
            missing.append(f"{mode} -> {func_name}")
    assert missing == [], f"Missing mode handler functions: {missing}"


# Test 3: run_full_mode exists (covers full + smart)
def test_full_mode_handler_exists():
    mod = _import_cycle()
    assert hasattr(mod, 'run_full_mode'), "ruppert_cycle.py must export run_full_mode()"
    assert callable(mod.run_full_mode)


# Test 4: run_cycle dispatches to correct handler (check source for mode strings)
def test_run_cycle_dispatches_all_modes():
    """Verify run_cycle source contains dispatch for all required modes."""
    mod = _import_cycle()
    source = inspect.getsource(mod.run_cycle)
    for mode in REQUIRED_MODES + list(FALLTHROUGH_MODES):
        assert f"'{mode}'" in source, (
            f"run_cycle() does not reference mode '{mode}'"
        )


# Test 5: No side effects on import (module-level code doesn't call KalshiClient)
def test_no_side_effects_on_import():
    """Importing ruppert_cycle should not instantiate KalshiClient or call APIs."""
    source = (REPO_ROOT / 'ruppert_cycle.py').read_text(encoding='utf-8')
    lines = source.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip lines inside function/class bodies (indented) and comments
        if stripped.startswith('#') or stripped.startswith('def ') or stripped.startswith('class '):
            continue
        if not line.startswith(' ') and not line.startswith('\t'):
            # Top-level line
            assert 'KalshiClient()' not in stripped, (
                f"Line {i}: KalshiClient() called at module level"
            )


# Test 6: Docstring modes match handler functions
def test_docstring_modes_match_handlers():
    """Modes in module docstring must match mode handler functions."""
    import re
    source = (REPO_ROOT / 'ruppert_cycle.py').read_text(encoding='utf-8')
    docstring_match = re.search(r'"""(.*?)"""', source, re.DOTALL)
    assert docstring_match, "Could not find module docstring"
    docstring = docstring_match.group(1)

    doc_modes = set()
    for line in docstring.splitlines():
        m = re.match(r'\s+(\w+)\s+—', line)
        if m:
            doc_modes.add(m.group(1))

    # Every documented mode should have a handler or be in run_cycle dispatch
    run_cycle_source = inspect.getsource(importlib.import_module('ruppert_cycle').run_cycle)
    for mode in doc_modes:
        assert f"'{mode}'" in run_cycle_source, (
            f"Mode '{mode}' documented but not in run_cycle dispatch"
        )
```

### 4.3 Tests That Need NO Changes

Any tests in other files that test `bot.strategy`, `main`, `capital`, etc. are unaffected — this refactor only touches `ruppert_cycle.py` and `tests/test_cycle_modes.py`.

---

## 5. Implementation Order

The Dev should implement in this order to keep the file working at every step:

### Step 1: Add CycleState dataclass (top of file, after imports)
- Add the dataclass definition
- No behavior change yet

### Step 2: Convert `save_state()` and `log_cycle()` signatures
- Add `mode`/`logs_dir`/`traded_tickers` params
- Update all call sites (search for `save_state()` and `log_cycle(`)
- File still runs as before (just passing the globals explicitly)

### Step 3: Extract init functions
- `load_traded_tickers(logs_dir)` — cut L106-144
- `check_circuit_breaker(logs_dir, capital)` — cut L146-159
- `compute_open_exposure(capital, buying_power)` — cut L161-167
- Replace cut sections with function calls

### Step 4: Extract reconciliation functions
- `run_orphan_reconciliation(client, logs_dir)` — cut L169-205
- `run_exposure_reconciliation(logs_dir, capital, buying_power)` — cut L207-221

### Step 5: Extract `run_position_check(client, state)`
- Cut L223-332
- This is the largest single block

### Step 6: Extract mode handlers
- `run_check_mode(state)` — cut L334-338
- `run_econ_prescan_mode(client, state)` — cut L341-452
- `run_weather_only_mode(state)` — cut L455-473
- `run_crypto_only_mode(state)` — cut L476-494
- `run_report_mode(state)` — cut L497-605
- `run_full_mode(client, state)` — cut L607-784

### Step 7: Write `run_cycle(mode)` orchestrator
- Assemble from the extracted pieces
- Move all module-level imperative code into this function

### Step 8: Add `if __name__ == '__main__'` block
- Remove the old module-level `MODE = sys.argv[1]...` line
- Add the 2-line main block

### Step 9: Update tests
- Replace `tests/test_cycle_modes.py` with new structure-based tests

### Step 10: Smoke test
- `python ruppert_cycle.py check` — should run position check and exit
- `python ruppert_cycle.py full` — should run full cycle
- `python -c "import ruppert_cycle"` — should NOT trigger any side effects

---

## 6. Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Import side effects from `config`, `logger`, etc. | `import ruppert_cycle` may still trigger config loading | Acceptable — config is read-only. The key fix is no API calls on import. |
| `from main import run_weather_scan` inside functions | Lazy imports are already used. Keep them inside mode handlers. | No change needed — these stay as-is inside the new functions. |
| `OPEN_POSITION_VALUE` is mutated between steps in full mode | Must ensure `state.open_position_value` is updated in `run_full_mode` after weather/crypto scans | Dev must preserve the `+= sum(...)` pattern on `state.open_position_value` |
| `traded_tickers` is a set mutated by multiple functions | `CycleState` holds the reference; functions mutate `state.traded_tickers` in place | This is intentional — sets are mutable. Document in CycleState docstring. |
| `sys.exit(0)` removal changes error behavior | If a mode handler raises, the old code would never reach later modes. New code must not fall through. | `run_cycle` uses if/elif dispatch — no fall-through possible. |
| Test import triggers side effects during transition | If tests import the module before refactor is complete | Run tests only after Step 8 is complete. |
| `direction` variable used by full mode notification | Currently a module-level var set in Step 2 | Move into `state.direction`, set inside `run_full_mode` |

---

## 7. Complexity Estimate

| Metric | Estimate |
|--------|----------|
| Files changed | 2 (`ruppert_cycle.py`, `tests/test_cycle_modes.py`) |
| Lines in ruppert_cycle.py | ~784 → ~820 (adds function defs, dataclass, main block; removes module-level code) |
| Net new lines | ~40 (function signatures, dataclass, orchestrator) |
| Lines moved | ~700 (virtually all existing code moves into functions) |
| Lines deleted | ~15 (module-level assignments that become function-local) |
| Test file | Complete rewrite (~120 lines → ~100 lines) |
| Risk level | LOW — pure structural refactor, no logic changes |
| Estimated Dev time | Single session |

---

## 8. Acceptance Criteria

1. `python ruppert_cycle.py full` produces identical output and behavior to current
2. `python ruppert_cycle.py check` produces identical output
3. `python ruppert_cycle.py crypto_only` produces identical output
4. `python -c "import ruppert_cycle"` completes without API calls or prints
5. All tests in `tests/test_cycle_modes.py` pass
6. `run_cycle('invalid')` raises `ValueError`
7. No module-level `KalshiClient()`, no module-level file reads (except path constants)
8. Every function has a docstring (1-line minimum)
