# Spec: crypto_15m — Daily Cap Raise + Circuit Breaker Hard Enforcement

**Date:** 2026-03-30
**Author:** Ruppert (Trader role)
**Status:** PENDING DEV
**Module:** `agents/ruppert/trader/crypto_15m.py`
**Config:** `environments/demo/config.py`

---

## Summary

Two changes to the `crypto_15m` module:

1. **Change 1 — Daily Cap Raise:** Increase `CRYPTO_15M_DAILY_WAGER_CAP_PCT` from `0.40` → `0.60`
2. **Change 2 — Circuit Breaker Hard Enforcement:** Flip `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY` from `True` → `False`, making the circuit breaker a hard stop instead of a log-only warning

---

## Change 1: Daily Wager Cap Raise (40% → 60%)

### Rationale

The current 40% backstop is described in config as "an execution bug safety net, not normal risk control." After the data collection phase, the binding risk control is the per-window cap (`CRYPTO_15M_WINDOW_CAP_PCT = 0.02`) and the strategy gate. The 40% cap is occasionally throttling legitimate high-frequency windows on active trading days. Raising to 60% gives the strategy gate more room to operate while the circuit breaker (Change 2) provides the daily hard-stop protection.

### Config Change

**File:** `environments/demo/config.py`

| Setting | BEFORE | AFTER |
|---|---|---|
| `CRYPTO_15M_DAILY_WAGER_CAP_PCT` | `0.40` | `0.60` |

```python
# BEFORE
CRYPTO_15M_DAILY_WAGER_CAP_PCT      = 0.40   # 40% backstop only — execution bug safety net, not normal risk control

# AFTER
CRYPTO_15M_DAILY_WAGER_CAP_PCT      = 0.60   # 60% backstop — raised to give strategy gate more room; CB is the daily hard stop
```

### Code Impact

No code changes required. `crypto_15m.py` already reads this config dynamically at call time:

```python
# Line ~551 in evaluate_crypto_15m_entry()
daily_wager_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_WAGER_CAP_PCT', 0.40)
```

The cap is enforced inside the `_window_lock` block at the "Check 1: Tier 2 daily wager backstop" step. The new 0.60 value will be picked up automatically on the next restart (or next hot-reload of config, if supported).

---

## Change 2: Circuit Breaker — Advisory → Hard Stop

### Rationale

Currently `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = True` means the circuit breaker **fires but does nothing** — it logs a warning and continues allowing entries. This defeats the purpose of having a circuit breaker. After 3 consecutive complete-loss windows, the module should halt for the remainder of the trading day to prevent runaway losses in adverse conditions.

### Config Change

**File:** `environments/demo/config.py`

| Setting | BEFORE | AFTER |
|---|---|---|
| `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY` | `True` | `False` |

```python
# BEFORE
CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = True   # True = log warning only, don't actually halt (data collection mode)

# AFTER
CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = False  # False = hard stop — halt all crypto_15m entries for rest of trading day
```

### Code Impact

**No code changes required.** The hard-stop path already exists in `crypto_15m.py`. The `cb_advisory` flag is read at call time and routes to either the warning path or the `CIRCUIT_BREAKER` skip path.

**Relevant code block** (inside `_window_lock`, ~line 570–590):

```python
# CURRENT BEHAVIOR (cb_advisory = True):
if _cb_consecutive_losses >= cb_n:
    if cb_advisory:
        logger.warning(
            '[crypto_15m] CIRCUIT BREAKER advisory: %d consecutive complete-loss windows '
            '(threshold=%d). Would halt but ADVISORY mode is on.',
            _cb_consecutive_losses, cb_n,
        )
        # Do NOT set _skip_reason — advisory mode continues trading  ← THIS IS THE PROBLEM
    else:
        _skip_reason = 'CIRCUIT_BREAKER'
```

**With `cb_advisory = False`:**
- When `_cb_consecutive_losses >= 3`, `cb_advisory` is `False`
- The `else` branch executes: `_skip_reason = 'CIRCUIT_BREAKER'`
- Further down, the function hits:
  ```python
  if _skip_reason:
      _log_decision(..., 'SKIP', _skip_reason, ...)
      return
  ```
- **Result:** Entry is blocked. All subsequent calls for that trading day will also be blocked (because `_cb_consecutive_losses` persists in memory and in the state file `logs/crypto_15m_circuit_breaker.json` until midnight rollover).

### Circuit Breaker Reset Mechanism

The CB state file is managed by `settlement_checker` (outside this module). The in-memory counter `_cb_consecutive_losses` is:
- Re-read from `logs/crypto_15m_circuit_breaker.json` on each **new window** (via the `win_key != _cb_last_window_ts` guard)
- Reset to 0 on winning windows (settlement_checker responsibility — not changed here)
- **Daily reset:** The state file must be cleared at midnight by settlement_checker for the daily hard-stop semantics to work correctly. **Dev should verify** that settlement_checker resets `consecutive_losses` to 0 at start of each trading day (or on first win after midnight).

### Behavior Table

| Consecutive Losses | BEFORE (Advisory=True) | AFTER (Advisory=False) |
|---|---|---|
| 0–2 | Trade normally | Trade normally |
| 3 (threshold hit) | Log warning, continue trading | Hard stop — block entry, log `CIRCUIT_BREAKER` |
| 4+ | Log warning, continue trading | Hard stop — continue blocking |
| Next win | CB counter resets (settlement_checker) | CB counter resets, trading resumes next window |

---

## Deployment Notes

1. **Config-only change** — both changes are single-line edits in `environments/demo/config.py`
2. **No code changes** to `crypto_15m.py` — the logic for both behaviors already exists
3. **Restart required** — config is read at module load time for some values; restart the main bot process after applying
4. **State file check** — before deploying, verify `logs/crypto_15m_circuit_breaker.json` exists and `consecutive_losses` is at a known-good value (not a stale trip from a prior bad run)
5. **Demo environment only** — these changes target `environments/demo/config.py`; prod config is a separate file and is not touched

---

## Risk Assessment

| Change | Risk | Mitigation |
|---|---|---|
| Cap 40% → 60% | Increases max daily exposure by 50% in adverse conditions | CB hard stop (Change 2) is the new daily backstop; window cap (2%) still binds per-window |
| CB Advisory → Hard | May halt trading on a bad day even if conditions improve | CB resets on next win; N=3 threshold is conservative; operator can manually reset state file if needed |

---

## Acceptance Criteria

- [ ] `CRYPTO_15M_DAILY_WAGER_CAP_PCT` reads `0.60` from config
- [ ] `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY` reads `False` from config
- [ ] On 3rd consecutive complete-loss window, next entry attempt logs `CIRCUIT_BREAKER` skip and returns without placing order
- [ ] Trading resumes after a winning window resets the CB counter
- [ ] Daily wager accumulates up to 60% of capital before `DAILY_WAGER_BACKSTOP` triggers (not 40%)
