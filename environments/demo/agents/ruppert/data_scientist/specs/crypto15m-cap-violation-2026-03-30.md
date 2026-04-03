# Spec: crypto_15m Daily Cap Violation — 2026-03-30

**Status:** Root cause confirmed — code fix required  
**Filed by:** Data Scientist (subagent)  
**Date:** 2026-03-30  
**Severity:** High — risk control gap (phantom cap enforcement)  

---

## Observed Facts

| Fact | Value |
|------|-------|
| Alert time | 2026-03-30 14:01 PDT |
| Alert message | "crypto_15m daily cap violated — $2,760 deployed vs $379 cap" |
| Total entries today (as of 2:01 PM) | 36 |
| Estimated capital (from arithmetic below) | ~$9,467 |
| Today's commit | b1b6834 — redesigned cap with WINDOW_CAP_PCT=0.02, DAILY_WAGER_CAP_PCT=0.40, CB N=3 advisory |

---

## Root Cause: Two Cap Variables, Zero Shared Definition

### The disconnect

There are **two separate cap systems** that do not reference each other:

**System A — enforcement engine** (`agents/ruppert/trader/crypto_15m.py`, line 1069):
```python
daily_wager_cap = capital * getattr(config, 'CRYPTO_15M_DAILY_WAGER_CAP_PCT', 0.40)
```
- Configured in `environments/demo/config.py` as `CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.40`
- At $9,467 capital → cap = **$3,787**
- This is the variable that actually blocks or trims entries (lines 1164–1167)

**System B — monitoring/alerting engine** (`agents/ruppert/data_scientist/data_agent.py`, line 299):
```python
'crypto_15m': capital * getattr(cfg, 'CRYPTO_15M_DAILY_CAP_PCT', 0.04),
```
- Reads `CRYPTO_15M_DAILY_CAP_PCT` — **this variable does not exist in `environments/demo/config.py`**
- Falls back to hardcoded default `0.04`
- At $9,467 capital → monitoring cap = **$378.68 ≈ $379**
- This is the value that appeared in the alert: `$379 cap`

### What this means

| | Enforcement (`crypto_15m.py`) | Monitoring (`data_agent.py`) |
|---|---|---|
| Variable | `CRYPTO_15M_DAILY_WAGER_CAP_PCT` | `CRYPTO_15M_DAILY_CAP_PCT` |
| Defined in config? | ✅ Yes — `0.40` | ❌ No — uses hardcoded default `0.04` |
| Cap at $9,467 capital | $3,787 | $379 |
| Blocks entries? | ✅ Yes (hard enforcement in lock) | ❌ No (alert only, never blocks) |

**The $379 alert cap is a ghost.** It is the `0.04` fallback default in `data_agent.py`, triggered because `CRYPTO_15M_DAILY_CAP_PCT` was never defined in `config.py`. The bot never knew about this cap — it enforced only the `0.40` cap ($3,787).

**The $2,760 deployed is real.** It is below the actual enforcement cap of $3,787, so `DAILY_WAGER_BACKSTOP` was never triggered. The enforcement engine functioned as designed — the monitoring engine measured it against a non-existent standard.

### Why $379 matches `0.04 × $9,467`

```
0.04 (default fallback) × $9,467 (capital) = $378.68 ≈ $379  ✓
```

This confirms the monitoring function never found `CRYPTO_15M_DAILY_CAP_PCT` in config and used `0.04`.

---

## Circuit Breaker Status (Secondary Finding)

**Configured:** `CRYPTO_15M_CIRCUIT_BREAKER_ADVISORY = True`  
**Effect:** When `_cb_consecutive_losses >= 3`, the code logs a warning but **does NOT set `_skip_reason`** (line ~1148 in `crypto_15m.py`):

```python
if _cb_consecutive_losses >= cb_n:
    if cb_advisory:
        logger.warning(
            '[crypto_15m] CIRCUIT BREAKER advisory: %d consecutive complete-loss windows ...',
            ...
        )
        # Do NOT set _skip_reason — advisory mode continues trading
    else:
        _skip_reason = 'CIRCUIT_BREAKER'
```

**Finding:** Circuit breaker is intentionally advisory-only in this commit. It never halts trading. 36 entries today is consistent with a bot that has no effective entry-count ceiling beyond the window cap.

---

## BEFORE / AFTER Spec

### BEFORE (current state as of b1b6834)

- `environments/demo/config.py` defines `CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.40` (used by enforcement)
- `environments/demo/config.py` does **not** define `CRYPTO_15M_DAILY_CAP_PCT`
- `data_agent.py:check_daily_cap_violations()` looks for `CRYPTO_15M_DAILY_CAP_PCT` and falls back to `0.04`
- Monitoring fires a cap-violation alert at ~$379 (4% of capital)
- Enforcement only triggers DAILY_WAGER_BACKSTOP at ~$3,787 (40% of capital)
- **Gap:** $3,787 − $379 = $3,408 of unmonitored headroom that the bot can fill without alerting David

### AFTER (required fix)

**Option 1 (minimal, preferred):** Add `CRYPTO_15M_DAILY_CAP_PCT` to `environments/demo/config.py` aligned with whatever David wants the *monitoring* threshold to be. This decouples the "alert me when X is reached" (monitoring) from the "hard-stop at Y" (enforcement). Example:

```python
# In environments/demo/config.py
CRYPTO_15M_DAILY_CAP_PCT = 0.04   # monitoring alert threshold (4% of capital ≈ $379)
                                   # distinct from DAILY_WAGER_CAP_PCT (0.40 = hard stop)
```

This would make the monitoring alert intentional and expected, not accidental. David is notified at $379 as an early-warning, enforcement still stops at $3,787.

**Option 2 (reconcile to single cap):** If the intent is one authoritative cap, align both variables:

```python
# In environments/demo/config.py
CRYPTO_15M_DAILY_CAP_PCT      = 0.40   # must match DAILY_WAGER_CAP_PCT
CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.40  # enforcement cap
```

And update `data_agent.py` to use `CRYPTO_15M_DAILY_WAGER_CAP_PCT` directly, eliminating the split.

**Option 3 (add monitoring-only cap as separate guard):** Treat the monitoring cap as an intentional early-warning system. Define it explicitly with a comment. Adjust value to whatever David wants as the trip point.

---

## Files Involved

| File | Role | Finding |
|------|------|---------|
| `agents/ruppert/trader/crypto_15m.py` | Entry enforcement | Uses `CRYPTO_15M_DAILY_WAGER_CAP_PCT` (0.40) — correctly defined, correctly enforced |
| `environments/demo/config.py` | Configuration source | Defines `CRYPTO_15M_DAILY_WAGER_CAP_PCT = 0.40` but NOT `CRYPTO_15M_DAILY_CAP_PCT` |
| `agents/ruppert/data_scientist/data_agent.py` | Monitoring / alerting | Reads `CRYPTO_15M_DAILY_CAP_PCT` — falls back to `0.04` default — produces $379 cap in alerts |

---

## Summary

**Root cause:** `data_agent.py:check_daily_cap_violations()` reads `CRYPTO_15M_DAILY_CAP_PCT` (undefined in config → defaults to `0.04` → $379). The enforcement engine uses `CRYPTO_15M_DAILY_WAGER_CAP_PCT` (`0.40` → $3,787). These are two different variable names with no shared definition. The $2,760 deployment was **within** the enforcement cap and was never blocked. The $379 alert threshold exists only as an accidental fallback.

**No code is broken.** Each system works as written. The problem is that two systems use different variable names that were never synchronized after the b1b6834 redesign.

**Recommended action for David:** Decide whether $379 (4%) is the intended monitoring trip-point or if it should match the enforcement cap. Then add the missing `CRYPTO_15M_DAILY_CAP_PCT` definition to `config.py`. Send to Dev for implementation.
