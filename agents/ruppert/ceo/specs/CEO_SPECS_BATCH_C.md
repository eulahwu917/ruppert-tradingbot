# CEO SPECS — Batch C
**Author:** Ruppert (CEO)  
**Date:** 2026-03-29  
**Status:** Ready for Dev  
**Priority order:** C6 (HIGH) → C1, C2, C3 (MEDIUM) → C4, C5 (LOW)

---

## C6 (HIGH): brief_generator.py reads trades from correct path — ruppert_cycle.py reads from wrong path

**Root cause confirmed:** After reading both files:

- `brief_generator.py` uses `TRADES_DIR = get_paths()['trades']` → resolves to `environments/demo/logs/trades/trades_YYYY-MM-DD.jsonl` ✅ **CORRECT**
- `ruppert_cycle.py` `load_traded_tickers()` reads from `logs_dir / f'trades_{date.today().isoformat()}.jsonl'` → resolves to `environments/demo/logs/trades_YYYY-MM-DD.jsonl` (flat, no `trades/` subdir) ❌ **WRONG**

`env_config.get_paths()['trades']` is the canonical path. `ruppert_cycle.py` must be updated to match.

**Files to modify:**
- `environments/demo/ruppert_cycle.py` — function `load_traded_tickers()`

**Change:**

In `load_traded_tickers(logs_dir)`, replace the trade log path construction on this line:

```python
# BEFORE (wrong — flat path, misses logs/trades/ subdir)
_trade_log_path = logs_dir / f'trades_{date.today().isoformat()}.jsonl'
```

```python
# AFTER (correct — matches canonical path from env_config + brief_generator)
# Import at top of load_traded_tickers (or add to module-level imports if not already present)
from agents.ruppert.env_config import get_paths as _get_paths_cycle
_trade_log_path = _get_paths_cycle()['trades'] / f'trades_{date.today().isoformat()}.jsonl'
```

**Also:** The `logs_dir` parameter is still valid for `state.json` and other flat files. Only the trade log path changes. Do not alter any other path references in `load_traded_tickers()`.

**Coordination note:** This is the same path fix as Trader Issue T4. Both `load_traded_tickers()` in `ruppert_cycle.py` and the Trader's equivalent function must end up reading from `get_paths()['trades'] / f'trades_{today}.jsonl'`. Verify T4 is implemented before or alongside this spec so both land on identical path logic.

**Test:**
1. Confirm `environments/demo/logs/trades/` directory exists and contains today's `trades_YYYY-MM-DD.jsonl`.
2. Run `ruppert_cycle.py check` in demo mode. Check stdout for `[Init] Loaded N open ticker(s) from today's log` — N must be non-zero if trades exist today.
3. Confirm `brief_generator.py _load_today_trades()` and `ruppert_cycle.py load_traded_tickers()` now reference the same file path by logging both resolved paths and comparing.
4. Run both and confirm traded_tickers sets are consistent (no phantom dedup gaps).

---

## C1 (MEDIUM): Orphaned start events in cycle_log.jsonl — no finally clause in run_cycle()

**Problem confirmed:** In `run_cycle()`, `log_cycle(mode, 'start')` fires unconditionally at the top. `log_cycle(mode, 'done', summary)` fires only on clean exit at the bottom. Any exception in the dispatch block (position check, mode handler, data agent audit, etc.) leaves a dangling `start` event with no matching `done` or `error` event.

**Files to modify:**
- `environments/demo/ruppert_cycle.py` — function `run_cycle()`

**Change:**

Wrap the body of `run_cycle()` from after the initial setup (rotate_logs, KalshiClient init, load_traded_tickers, circuit breaker check) through to `log_cycle(mode, 'done', summary)` in a `try/finally` block. The `log_cycle(mode, 'start')` call and early-exit circuit breaker path stay outside.

```python
def run_cycle(mode):
    print(f"\n{'='*60}")
    print(f"  RUPPERT CYCLE  mode={mode.upper()}  {ts()}")
    print(f"{'='*60}")
    log_cycle(mode, 'start')  # ← stays here, outside try

    try:
        rotate_logs()
    except Exception as e:
        print(f"[Logger] Log rotation skipped: {e}")

    client = KalshiClient()
    logs_dir = Path(__file__).parent / 'logs'
    logs_dir.mkdir(exist_ok=True)

    traded_tickers = load_traded_tickers(logs_dir)

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

    # ── NEW: wrap dispatch body in try/finally ─────────────────────────────
    try:
        # Data Agent: daily historical audit (once per day, non-fatal)
        try:
            from agents.ruppert.data_scientist.data_agent import run_historical_audit
            run_historical_audit(since_date=(date.today() - timedelta(days=30)).isoformat())
        except Exception as _ha_err:
            log_activity(f'[DataAgent] Historical audit failed: {_ha_err}')

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

        # Data Agent: post-scan audit (non-fatal)
        if mode in ('full', 'smart', 'crypto_only', 'weather_only', 'econ_prescan'):
            try:
                from agents.ruppert.data_scientist.data_agent import run_post_scan_audit
                _audit = run_post_scan_audit(mode='post_cycle')
                _iss = _audit.get('issues_found', 0)
                if _iss:
                    print(f'  [DataAgent] {_iss} issue(s) found and handled')
            except Exception as _da_err:
                log_activity(f'[DataAgent] Post-scan audit failed: {_da_err}')

        save_state(logs_dir, state.traded_tickers, mode)
        log_cycle(mode, 'done', summary)

    except Exception as e:
        # Always fire a closing log event — prevents orphaned 'start' entries
        log_cycle(mode, 'error', {'exception': str(e)})
        raise  # re-raise so the scheduler sees non-zero exit
```

**Critical:** The `raise` at the end of the `except` block is mandatory. We log the error AND propagate it so Windows Task Scheduler records a failure. Do not swallow the exception.

**Test:**
1. Manually call `run_cycle('full')` with a monkey-patched exception injected at the top of `run_full_mode()`.
2. Inspect `environments/demo/logs/cycle_log.jsonl` — must contain a `start` event followed by an `error` event with `exception` key. Must have NO dangling `start`-only entry.
3. Confirm the process exits non-zero (Task Scheduler will flag it as failed).
4. Run a clean cycle — confirm `done` event still fires normally.

---

## C2 (MEDIUM): Bare econ imports in ruppert_cycle.py need explicit path guard

**Problem confirmed:** `run_econ_prescan_mode()` contains:
```python
from economics_client import get_upcoming_releases as _get_upcoming
from economics_scanner import find_econ_opportunities as _find_econ
```
These are bare module names that only resolve because `_ENV_ROOT` (`environments/demo/`) is on `sys.path` from the module-level guard. If the import order changes, or if this function is called from a different entry point, it will fail silently with `ModuleNotFoundError`.

**Files to modify:**
- `environments/demo/ruppert_cycle.py` — function `run_econ_prescan_mode()`

**Change:**

Add an explicit `sys.path` guard at the top of `run_econ_prescan_mode()`, immediately before the bare imports. Insert the following block:

```python
def run_econ_prescan_mode(client, state):
    """Econ prescan: check releases, trade if any today.
    Returns {'econ_trades': int, 'reason': str (optional)}.
    """
    print("\n[econ_prescan] Checking for econ releases today...")
    _econ_trades = 0
    try:
        # ── Path guard: economics_client.py and economics_scanner.py live in
        # environments/demo/ (not agents/ruppert/). They cannot be moved without
        # breaking their internal relative imports. We keep bare imports but
        # ensure _ENV_ROOT is on sys.path here as a defensive local guard,
        # in case this function is ever called from a context where the module-level
        # guard at the top of ruppert_cycle.py has not run.
        import sys as _sys
        _econ_env_root = str(Path(__file__).parent)
        if _econ_env_root not in _sys.path:
            _sys.path.insert(0, _econ_env_root)

        from economics_client import get_upcoming_releases as _get_upcoming
        from economics_scanner import find_econ_opportunities as _find_econ
        # ... rest of function unchanged
```

No other changes to the function body. The bare import style is acceptable here — the comment documents why.

**Test:**
1. Temporarily remove the module-level `sys.path` guard from the top of `ruppert_cycle.py` (the `_ENV_ROOT` block).
2. Call `run_econ_prescan_mode()` directly.
3. Confirm it still imports and runs without `ModuleNotFoundError`.
4. Restore the module-level guard after confirming.

---

## C3 (MEDIUM): weather_only mode missing traded_tickers and open_position_value

**Signature confirmed:** `run_weather_scan()` in `agents/ruppert/trader/main.py` line 253 has signature:
```python
def run_weather_scan(dry_run=True):
```
It does **not** currently accept `traded_tickers` or `open_position_value` kwargs. Instead, it computes open exposure internally via `max(0.0, total_capital - get_buying_power())` and uses `traded_tickers=None` hardcoded in `should_enter()`.

This means `run_weather_only_mode()` cannot pass those args to the current `run_weather_scan()` signature without a signature change in `main.py`.

**This spec requires TWO coordinated changes:**

### Part A — Update `run_weather_scan()` signature in `agents/ruppert/trader/main.py`

**Files to modify:** `agents/ruppert/trader/main.py`

Add `traded_tickers=None` and `open_position_value=None` to the `run_weather_scan()` signature. When `open_position_value` is provided (not `None`), use it instead of computing from `get_buying_power()`. When `traded_tickers` is provided, pass it through to `should_enter()`.

```python
def run_weather_scan(dry_run=True, traded_tickers=None, open_position_value=None):
    """Run weather market scan and execute trades."""
    log_activity("[Weather] Starting scan...")
    if traded_tickers is None:
        traded_tickers = set()
    try:
        # ... existing KalshiClient init, market fetch, etc. unchanged ...

        # ── Strategy gate: filter through should_enter() ────────────────────
        _weather_daily_cap = total_capital * getattr(config, 'WEATHER_DAILY_CAP_PCT', 0.07)
        # Use caller-provided open_position_value if given (avoids redundant API call).
        # Fall back to computing from buying_power if not provided.
        if open_position_value is not None:
            _open_exposure = open_position_value
        else:
            try:
                _open_exposure = max(0.0, total_capital - get_buying_power())
            except Exception:
                _open_exposure = 0.0

        # In should_enter() call, pass traded_tickers instead of None:
        decision = should_enter(
            signal, total_capital, deployed_today,
            module='weather',
            module_deployed_pct=_weather_deployed_this_cycle / total_capital if total_capital > 0 else 0.0,
            traded_tickers=traded_tickers,  # ← was hardcoded None
        )
```

Dev must locate the exact `should_enter()` call within the `run_weather_scan()` loop and update `traded_tickers=None` → `traded_tickers=traded_tickers`. Also find the `_open_exposure` computation and apply the conditional above.

### Part B — Update `run_weather_only_mode()` call in `ruppert_cycle.py`

**Files to modify:** `environments/demo/ruppert_cycle.py`

```python
# BEFORE
_weather_results = _run_weather(dry_run=state.dry_run)

# AFTER
_weather_results = _run_weather(
    dry_run=state.dry_run,
    traded_tickers=state.traded_tickers,
    open_position_value=state.open_position_value,
)
```

**Test:**
1. Confirm `run_weather_scan()` signature now accepts all three kwargs.
2. Run `ruppert_cycle.py weather_only` in demo mode with a non-empty `state.traded_tickers`. Confirm that a ticker already in `traded_tickers` is not traded again in the weather scan.
3. Confirm `open_position_value` is used from state (add a print statement temporarily to verify the value passed in equals the value in `state`).
4. Run `ruppert_cycle.py full` — confirm `run_weather_scan()` still works with no args (old call path in `run_full_mode()` passes no kwargs; it must still compute exposure internally via the `None` fallback).

---

## C4 (LOW): 'smart' mode is identical to full mode — document with TODO

**Problem confirmed:** In `run_cycle()` dispatch:
```python
elif mode in ('full', 'smart'):
    summary = run_full_mode(client, state)
```
`smart` routes to `run_full_mode()` — intended as a lightweight refresh but never implemented. It is not currently scheduled.

There is also a comment in the data agent block referencing smart:
```python
# Note: 'smart' mode triggers lighter synthesis (pnl_cache + positions only)
```
This comment is aspirational — it does not reflect actual behavior.

**Files to modify:**
- `environments/demo/ruppert_cycle.py`

**Change:**

No behavior change. Add a TODO comment in the dispatch block. Also update the misleading data agent comment.

```python
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
elif mode == 'full':
    summary = run_full_mode(client, state)
elif mode == 'smart':
    # TODO (C4): 'smart' mode is not yet implemented.
    # Intended behavior: lightweight refresh — smart money signal + position check only,
    # skipping full weather/crypto scans. Not currently scheduled.
    # For now, falls back to full mode to avoid silent no-ops.
    # Implement as run_smart_mode() when scheduling requires it.
    summary = run_full_mode(client, state)
else:
    raise ValueError(f'Unknown mode: {mode}')
```

Also update the data agent comment below the dispatch block:

```python
# Note: 'smart' mode currently falls back to full mode (see TODO C4 above).
# When run_smart_mode() is implemented, update this condition accordingly.
if mode in ('full', 'smart', 'crypto_only', 'weather_only', 'econ_prescan'):
```

**Test:**
1. No behavior change expected — run `ruppert_cycle.py smart` and confirm it produces identical output to `full`.
2. Confirm the TODO comment is present in the file as committed.

---

## C5 (LOW): run_report_mode() writes pending_optimizer_review.json directly (boundary violation)

**Problem confirmed:** In `run_report_mode()`:
```python
review_file = state.logs_dir / 'pending_optimizer_review.json'
review_data = {'date': today_str, 'losses': losses, 'total_loss': total_loss}
review_file.write_text(json.dumps(review_data, indent=2), encoding='utf-8')
```
CEO is writing a file that Data Scientist owns. This violates agent ownership boundaries.

**synthesizer.py confirmed:** Does NOT handle `OPTIMIZER_REVIEW_NEEDED` event type. Only handles `ALERT_CANDIDATE` and `STATE_UPDATE`. Data Scientist must add this handler — noted below.

**Files to modify:**
- `environments/demo/ruppert_cycle.py` — function `run_report_mode()`
- `agents/ruppert/data_scientist/synthesizer.py` — add `OPTIMIZER_REVIEW_NEEDED` handler *(Data Scientist task)*

### Part A — ruppert_cycle.py (CEO change)

Replace the direct file write with a `log_event()` call:

```python
# BEFORE (boundary violation — CEO writing Data Scientist's file)
review_file = state.logs_dir / 'pending_optimizer_review.json'
review_data = {
    'date':       today_str,
    'losses':     losses,
    'total_loss': total_loss,
}
review_file.write_text(json.dumps(review_data, indent=2), encoding='utf-8')
print(f"  Wrote pending_optimizer_review.json — "
      f"{len(losses)} loss(es) totaling ${total_loss:.2f}")
```

```python
# AFTER (CEO emits event; Data Scientist synthesizes the file)
log_event('OPTIMIZER_REVIEW_NEEDED', {
    'date':       today_str,
    'losses':     losses,
    'total_loss': total_loss,
})
print(f"  Emitted OPTIMIZER_REVIEW_NEEDED — "
      f"{len(losses)} loss(es) totaling ${total_loss:.2f}")
```

The `push_alert('optimizer', alert_msg)` call immediately after can remain unchanged.

### Part B — synthesizer.py (Data Scientist task, not CEO)

Data Scientist must add a `synthesize_optimizer_review()` function to `synthesizer.py` and call it from `run_synthesis()`. Spec for Data Scientist:

> Add handler for `OPTIMIZER_REVIEW_NEEDED` events. Read all such events from today's event log. Take the one with the highest `total_loss` (or latest timestamp if tie). Write `logs/truth/pending_optimizer_review.json` with `{date, losses, total_loss}`. This file is already read by the optimizer — format must stay identical. Call this synthesizer from `run_synthesis()` alongside the existing `synthesize_alerts()` and `synthesize_pnl_cache()` calls.

**Test:**
1. Run `ruppert_cycle.py report` in demo mode with a trade log containing at least one losing exit (negative `realized_pnl`).
2. Confirm `OPTIMIZER_REVIEW_NEEDED` event appears in `logs/raw/events_YYYY-MM-DD.jsonl`.
3. Confirm `ruppert_cycle.py` no longer directly writes `pending_optimizer_review.json`.
4. Run `synthesizer.py` standalone — confirm `logs/truth/pending_optimizer_review.json` is created with the correct `{date, losses, total_loss}` payload. *(Requires Part B to be implemented by Data Scientist first.)*
5. Until Part B is implemented: confirm the event is emitted and the old direct-write code is gone. Note in QA log that `pending_optimizer_review.json` will not be created until Data Scientist ships Part B.

---

## Implementation Order for Dev

| Priority | Issue | Dependency |
|----------|-------|------------|
| 1st | C6 — trade path fix | None. Standalone. |
| 2nd | C1 — finally clause | None. Standalone. |
| 3rd | C3 — weather kwargs | Requires main.py signature change (Part A) before ruppert_cycle.py change (Part B). |
| 4th | C2 — econ path guard | None. Standalone. |
| 5th | C4 — smart TODO | None. Comment-only change. |
| 6th | C5 — optimizer boundary | Part A (ruppert_cycle.py) is standalone. Part B (synthesizer.py) is a Data Scientist task. |

C3 is two-file — Dev must ship both parts atomically or risk a broken call between weather_only mode and the updated signature.
