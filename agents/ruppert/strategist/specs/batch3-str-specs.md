# Batch 3 Strategist Specs
_Authored: 2026-04-04 | Strategist → Dev pipeline_
_Status: Ready for adversarial review_

---

## B3-STR-1: Route `get_module_state` and `set_module_state` through `_rw_locked()`

**File:** `agents/ruppert/trader/circuit_breaker.py`

### Problem

`get_module_state()` (lines ~146–166) calls `_read_full_state()` and `_write_full_state()` directly — no file lock. `set_module_state()` (lines ~168–175) does the same: reads then writes, unlocked. Meanwhile `increment_consecutive_losses()` and `reset_consecutive_losses()` are already correctly routed through `_rw_locked()`.

This creates a race: the WS feed (calling `increment_consecutive_losses`) holds an exclusive lock and writes `consecutive_losses = N`, but a concurrent scan cycle calling `get_module_state()` (for a day-reset check) can read stale data and immediately overwrite the file with `consecutive_losses = 0` via the unlocked `_write_full_state()`. Net result: the CB counter silently resets mid-session and may never trip.

### Fix

**`set_module_state()`** — replace the current read→mutate→write sequence with a `_rw_locked()` call. The lock scope should cover the full read-modify-write cycle: read existing full state under lock, set `state[module] = new_mod_state`, write back, release lock.

Concrete change: instead of calling `_read_full_state()` and `_write_full_state()` directly, define an inner `_mutate(state)` function that does `state[module] = new_mod_state`, then pass it to `_rw_locked(_state_path(), _mutate)`. This is the same pattern already used in `increment_consecutive_losses()` and `reset_consecutive_losses()`.

**`get_module_state()`** — the day-reset write path (the branch that fires when `mod.get('date') != today`) must also be protected. There are two valid approaches:

- **Option A (simpler):** Route the entire function through `_rw_locked()`. Inside the lock, perform the read, check the date, conditionally reset, and return the result via a mutable cell (same `_new_count` cell pattern used elsewhere). The normal (no-reset) read path stays inside the lock but exits quickly, so lock contention is minimal.
- **Option B (minimal change):** Only lock the day-reset branch. If the date matches today, return `dict(mod)` without locking (reads are not atomic but this is acceptable for display/decision reads). If the date doesn't match, acquire the lock before writing the fresh default.

**Recommended approach: Option A.** The function is not called in a tight loop, so holding the lock for the duration of a read-plus-conditional-write is fine. Consistency with the rest of the file is worth more than micro-optimizing this path.

### What Must Not Change

- The public signatures of `get_module_state(module)` and `set_module_state(module, new_mod_state)` must stay identical.
- The day-reset logic (detect date mismatch → return fresh default) must remain.
- `_rw_locked()` itself must not be modified.
- `increment_consecutive_losses()` and `reset_consecutive_losses()` are already correct — do not touch them.

### Acceptance Criteria

1. `set_module_state()` no longer calls `_read_full_state()` or `_write_full_state()` directly.
2. `get_module_state()` no longer calls `_write_full_state()` directly (the day-reset write goes through `_rw_locked()`).
3. A concurrent call to `increment_consecutive_losses()` and `get_module_state()` on the same module cannot overwrite each other's state — both hold the same exclusive lock and will serialize.
4. No behaviour change under non-concurrent conditions (single caller, normal operation).

---

## B3-STR-2: Fix key name mismatch — `loss_today` vs `net_loss_today`

**File:** `environments/demo/ruppert_cycle.py`

### Problem

`check_loss_circuit_breaker()` in `strategy.py` (line ~700) wraps `check_global_net_loss()` from `circuit_breaker.py` and normalizes the key name: the returned dict uses `'loss_today'` (not `'net_loss_today'`). This normalization is correct and intentional — the docstring explicitly says "callers expect `'loss_today'`".

However, `ruppert_cycle.py` around line 229 reads `_cb['loss_today']` for the display path — which *is correct*. The key name is NOT the bug.

**Revised diagnosis after reading the actual code:**

The display print at line 229–230 reads:
```python
elif _cb['loss_today'] > 0:
    print(f"  [LossCheck] Today's losses: ${_cb['loss_today']:.2f} — within threshold")
```

This is correct — `check_loss_circuit_breaker()` returns `loss_today`. **There is no key mismatch in `ruppert_cycle.py` itself.**

The actual bug is in the `log_event` call at line 225:
```python
log_event('CIRCUIT_BREAKER', {
    'reason': _cb['reason'],
    'loss_today': _cb.get('loss_today', 0),
})
```

This is also correct usage. The key in the returned dict from `check_loss_circuit_breaker()` is `'loss_today'` (strategy.py line ~714 translates `net_loss_today` → `loss_today`), and `ruppert_cycle.py` uses `'loss_today'` throughout.

**Conclusion:** The "$0 display" bug is NOT a key name mismatch in `ruppert_cycle.py`. The translation layer in `strategy.py:check_loss_circuit_breaker()` correctly maps `net_loss_today` → `loss_today` before returning to `ruppert_cycle.py`. The display reading `_cb['loss_today']` is correct.

### Where the Real Bug Likely Is

If the display always shows $0, the root cause is one of:
1. The circuit breaker is not being reached (tripped=False and loss_today=0), meaning trade log records don't have `action: 'exit'` or `action: 'settle'` — check the trade log format.
2. `pnl` fields on exit/settle records are missing or zero.
3. `check_global_net_loss()` in `circuit_breaker.py` is reading the wrong trade log path.

### Spec (narrowed)

Do NOT change `ruppert_cycle.py` line 229. The key name `'loss_today'` is correct there.

**Instead, Dev should add a diagnostic log line** in `check_global_net_loss()` (circuit_breaker.py) that logs how many `exit`/`settle` records were found and their pnl sum. This will expose whether the issue is in the log-reading path or in data absence. This is a one-line `logger.info()` addition, not a bug fix — it's a diagnostic to identify the actual root cause before patching.

**Alternatively (if David wants to force-expose the value):** In the `run_circuit_breaker_check()` function in `ruppert_cycle.py`, add `logger.info('[LossCheck] cb result: %s', _cb)` before the `if _cb['tripped']` branch. This will log the full returned dict every cycle, making it immediately clear whether `loss_today` is 0 because the CB returns it as 0 or because the key is missing.

### What Must Not Change

- Do not change key names in `ruppert_cycle.py` — they are correct.
- Do not change the `check_loss_circuit_breaker()` wrapper in `strategy.py` — the normalization is intentional and documented.
- Do not change the `check_global_net_loss()` return schema in `circuit_breaker.py`.

### Acceptance Criteria

1. Dev confirms whether `net_pnl` in `check_global_net_loss()` is computing a non-zero value during sessions with real P&L.
2. If non-zero, the value propagates correctly through to the display print.
3. If zero, the root cause (missing pnl fields on exit records, wrong log path, etc.) is identified and a separate spec is written.

---

## Strategist Notes for Adversarial Reviewer

**B3-STR-1** is a clean, well-scoped fix. The `_rw_locked()` pattern is already established in the file and the extension is mechanical. The only judgment call is Option A vs B for `get_module_state()` — I recommend A (lock the whole function) because it's simpler and consistent. If the reviewer disagrees, Option B is acceptable.

**B3-STR-2** is more nuanced. The original bug report says "key name is wrong" but after reading the actual code, the key name in `ruppert_cycle.py` (`loss_today`) is correct — `strategy.py:check_loss_circuit_breaker()` already translates `net_loss_today` → `loss_today` before returning. The "$0 display" symptom has a different root cause that requires investigation before a code fix can be written. I've scoped this as a diagnostic task rather than a one-line patch, to avoid fixing the wrong thing.

If the reviewer or Dev believes I've misread the call chain, they should trace: `ruppert_cycle.py:run_circuit_breaker_check()` → `strategy.py:check_loss_circuit_breaker()` → `circuit_breaker.py:check_global_net_loss()` and confirm the key translation at each boundary.
