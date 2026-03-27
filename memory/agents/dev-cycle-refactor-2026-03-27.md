---
name: Dev Cycle Refactor Handoff
description: Developer handoff for ruppert_cycle.py refactor from top-level script to function-based architecture
type: project
---

# Dev Handoff — ruppert_cycle.py Refactor (2026-03-27)

**Status:** COMPLETE — awaiting QA validation

## What was done

Refactored `ruppert_cycle.py` from a 784-line top-level script (all code runs on import) to a function-based architecture with a `CycleState` dataclass and `run_cycle(mode)` orchestrator.

### Changes made

**ruppert_cycle.py:**
- Added `CycleState` dataclass (lines ~35-45) holding mode, dry_run, logs_dir, traded_tickers, open_position_value, actions_taken, capital, buying_power, direction
- Changed `log_cycle(event, data)` → `log_cycle(mode, event, data)` — mode is now an explicit param
- Changed `save_state()` → `save_state(logs_dir, traded_tickers, mode)` — no more globals
- Extracted `load_traded_tickers(logs_dir)` — returns set of traded tickers
- Extracted `check_circuit_breaker(logs_dir, capital)` — returns None or dict
- Extracted `compute_open_exposure(capital, buying_power)` — returns float
- Extracted `run_orphan_reconciliation(client, logs_dir)`
- Extracted `run_exposure_reconciliation(logs_dir, capital, buying_power)`
- Extracted `run_position_check(client, state)` — returns actions_taken list
- Extracted mode handlers: `run_check_mode(state)`, `run_econ_prescan_mode(client, state)`, `run_weather_only_mode(state)`, `run_crypto_only_mode(state)`, `run_report_mode(state)`, `run_full_mode(client, state)`
- Created `run_cycle(mode)` orchestrator that wires everything together
- Added `if __name__ == '__main__'` block
- Removed all module-level imperative code (no KalshiClient(), no API calls, no file reads on import)
- Removed global `MODE`, `DRY_RUN` references in favor of `state.*` params
- Removed `sys.exit(0)` from mode handlers (flow returns to orchestrator)

**tests/test_cycle_modes.py:**
- Complete rewrite from string-grep tests to structural verification
- 6 tests: run_cycle_exists, mode_handler_functions_exist, full_mode_handler_exists, run_cycle_dispatches_all_modes, no_side_effects_on_import, docstring_modes_match_handlers
- Tests import the module via `importlib.util` (safe — no side effects)

### Verification

- Syntax check: PASS
- Full test suite: 20/20 PASS (including 6 new cycle mode tests)
- Zero trading logic changes — all thresholds, decision paths, print statements, log_activity calls preserved
- File still works as: `python ruppert_cycle.py full / check / crypto_only / etc.`

### Files changed
- `ruppert_cycle.py` — structural refactor
- `tests/test_cycle_modes.py` — test rewrite

### Known considerations
- `config` and `logger` imports still happen at module level (read-only, acceptable per spec)
- Lazy imports inside mode handlers preserved as-is (e.g., `from main import run_weather_scan`)
- `state.open_position_value` is mutated in `run_full_mode` after weather/crypto scans (preserves original `OPEN_POSITION_VALUE += sum(...)` pattern)
