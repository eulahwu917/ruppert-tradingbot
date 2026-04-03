# Bug Report: decisions_1d.jsonl Silent Write Failure
**Date:** 2026-04-02  
**Authored by:** Dev  
**Status:** Investigation complete — awaiting CEO review before any fix

---

## Summary

`decisions_1d.jsonl` contains only 2 bytes (`\r\n`) for April 2, 2026. Although 91 buy trades with `module=crypto_threshold_daily_btc/eth` were logged today, **zero** of those trades went through `evaluate_crypto_1d_entry()`. The `_log_decision()` function was never called. This is not a write failure — it is a **code path mismatch**: the 91 trades came through a different execution path that has no decision logging.

---

## Root Cause (Confirmed)

### Two separate issues, not one:

---

### Issue 1: Global circuit breaker blocked crypto_1d cycles all morning

The `run_cycle()` function in `ruppert_cycle.py` calls `check_circuit_breaker()` **before** dispatching to any mode handler. Both crypto_1d scheduled runs today tripped the global loss circuit breaker and exited before `evaluate_crypto_1d_entry()` was ever called:

```
cycle_log.jsonl:
  2026-04-02 06:30:02  crypto_1d  circuit_breaker  "Loss circuit breaker tripped: $3078.85 losses today exceed 5% of capital ($509.97)"
  2026-04-02 10:30:02  crypto_1d  circuit_breaker  "Loss circuit breaker tripped: $5543.76 losses today exceed 5% of capital ($492.10)"
```

`run_cycle()` calls `sys.exit(0)` when the circuit breaker trips, so `run_crypto_1d_mode()` → `run_crypto_1d_scan()` → `evaluate_crypto_1d_entry()` → `_log_decision()` never execute. No decisions to log.

---

### Issue 2: The 91 "crypto_threshold_daily" trades came from position_monitor.py, not crypto_threshold_daily.py

The 91 buy entries in `trades_2026-04-02.jsonl` tagged `module=crypto_threshold_daily_btc/eth` were **not** placed by `evaluate_crypto_1d_entry()`. They were placed by `position_monitor.py`'s WebSocket feed handler, which:

- Tags trades with `module='crypto_threshold_daily_*'` but `source='crypto'` (or `source='ws_position_tracker'`)
- Appears in the activity log as `[WS-CRYPTO] Entered KXBTCD-... YES @ Xc` entries
- Has **no call** to `_log_decision()` anywhere in its code path

This is why the decision log is empty despite 91 trades existing. The decision log only receives entries from `evaluate_crypto_1d_entry()`, which runs in a separate scheduled cycle (`crypto_1d` mode) that was blocked by circuit breaker both times today.

**Evidence:**
- `activity_2026-04-02.log` has zero `[Crypto1D]` entries (the prefix used by `evaluate_crypto_1d_entry` path)
- `activity_2026-04-02.log` has 45 `[WS-CRYPTO] Entered KXBTCD/KXETHD` entries (from position_monitor.py)
- All 91 trades have `source: "crypto"` or `source: "ws_position_tracker"`, never `source: "crypto_1d"`
- Trade timestamps (02:30, 03:45, 04:59...) are outside the 09:30–11:30 / 13:30–14:30 ET entry windows that `evaluate_crypto_1d_entry` enforces

---

## What the decisions_1d.jsonl File State Means

The file's `LastWriteTime` is **2026-04-01 17:17:36**. This is when the daily log archive ran and reset `decisions_1d.jsonl` to an empty file (with a trailing `\r\n`). The archive for April 1 (`environments/demo/logs/archive/2026-04-01/decisions_1d.jsonl`, 1895 bytes) contains valid SKIP entries from the April 1 06:30 scan. The file is working correctly — it just has nothing to write today because the crypto_1d cycles never ran past the circuit breaker.

---

## Does This Affect band_daily?

**`decisions_band.jsonl` does not exist** in `environments/demo/logs/`. This means `crypto_band_daily.py`'s `_log_band_decision()` has also never written any entries (no band module cycle has run, or band also trips circuit breaker). This is consistent with the pattern — the crypto_band_daily module also runs via `run_crypto_scan()` in `crypto_only` mode, and that mode has been hitting the circuit breaker repeatedly today (08:00, 10:00, 12:00).

**Band daily is affected by the same Issue 1** (circuit breaker blocking all crypto scans).

---

## Are SKIP and ENTER Both Missing?

**Both are missing** from today's log. However, this is because `evaluate_crypto_1d_entry()` was never called at all — not because `_log_decision()` has a write bug.

On **April 1** (confirmed from archive), `_log_decision()` worked correctly: `decisions_1d.jsonl` had 1895 bytes of valid SKIP entries after the 06:30 scan ran.

The `_log_decision()` function itself is **not broken**.

---

## The Exception-Swallowing Question

The `_log_decision()` function does wrap its write in `try/except Exception as e: logger.warning(...)`. If `logger` were uninitialized, the warning would silently fail too. However, this is **not the failure mode here** — the function is simply never called. The exception swallowing would only matter if the path/write itself failed, which it has not (as evidenced by April 1's valid archive).

That said, this pattern remains a latent risk: if `DECISION_LOG_PATH` were ever wrong or the directory were missing, there would be no visible error. This is worth noting for hardening.

---

## Path Resolution: Is It Correct?

`DECISION_LOG_PATH` is set at module import time via `_get_paths()['logs'] / 'decisions_1d.jsonl'`. `env_config.get_paths()` resolves using `OPENCLAW_WORKSPACE` env var or `Path.home() / '.openclaw' / 'workspace'` — never relative paths. This is **working correctly** and is not related to the empty file.

---

## Other Log Paths That May Have the Same Issue

Any decision log that is only written by a module callable from `ruppert_cycle.py` modes that trigger the circuit breaker will be empty on heavy-loss days. Specifically:

| Log File | Written By | Mode | Affected Today? |
|---|---|---|---|
| `decisions_1d.jsonl` | `crypto_threshold_daily.py` | `crypto_1d` | ✅ Yes — CB tripped |
| `decisions_band.jsonl` | `crypto_band_daily.py` | `crypto_only` | ✅ Yes — CB tripped most of day |
| `decisions_15m.jsonl` | `crypto_15m.py` | `crypto_only` | ⚠️ Partially (some cycles ran after CB cleared ~14:00) |

---

## Exact Fix Needed

**There are two separate issues that warrant two separate fixes:**

**Fix 1 (High Priority — Logging Gap):** `position_monitor.py`'s WS-CRYPTO entry handler places `crypto_threshold_daily_*` trades but never calls `_log_decision()`. These trades should also emit decision log entries. Add a call to `_log_decision()` (or a shim/import of it) in the WS-CRYPTO entry path in `position_monitor.py`, so that all trades tagged `module=crypto_threshold_daily_*` are captured in `decisions_1d.jsonl` regardless of which code path placed them.

**Fix 2 (Hardening — Exception Swallowing):** The `_log_decision()` try/except silently eats write errors. Change the except block to also `print()` the error to stdout (in addition to `logger.warning`) so failures appear in Task Scheduler's captured output even if the logger isn't properly initialized.

**Note:** The circuit breaker itself working correctly is expected behavior — it is designed to halt new entries, not to log decisions for trades that weren't evaluated. Fix 1 addresses the underlying data completeness gap.

---

## Handoff to QA

This spec is complete. Root cause confirmed, not guessed. No production files were modified.

**CEO to review before any code changes are made.**

Questions for CEO / David:
1. Should `position_monitor.py` WS-CRYPTO entries call `_log_decision()`? This requires importing `crypto_threshold_daily.py` into `position_monitor.py` (adds a dependency) or extracting `_log_decision()` to a shared helper.
2. Is the circuit breaker loss figure ($3078 today) accurate? The global CB reads from trade logs; if those figures are inflated by the poisoned/dedup backup incident earlier today (see `trades_2026-04-02.poisoned.jsonl`), the CB may be miscalculating losses.
