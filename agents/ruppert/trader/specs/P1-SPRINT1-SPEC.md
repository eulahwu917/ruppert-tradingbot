# P1 Sprint 1 — Signal Integrity Spec
**Sprint:** P1-1  
**Date:** 2026-04-03  
**Authored by:** Trader  
**Revised:** 2026-04-03 (post-adversarial-review)  
**Issues:** ISSUE-096, ISSUE-032, ISSUE-129, ISSUE-114, ISSUE-069, ISSUE-116 (placeholder), ISSUE-104, ISSUE-105  
**Reviewer:** David (please review before Dev starts)

---

## Revision Summary (2026-04-03)

Five specs revised following adversarial review (`memory/agents/p1-sprint1-adversarial-review.md`):

| Issue | What Changed |
|-------|-------------|
| **ISSUE-096** | Identified BOTH reconnect paths (error-based AND timeout-based). Variable placement clarified (outside `while True`). Reset anchor corrected (after `_write_heartbeat()` inside successful `async with ws:` block). Pseudocode updated for both paths. |
| **ISSUE-114** | Replaced `assert` with `raise ValueError` (immune to `-O` flag). Error message now includes actual sum so it's debuggable. Language updated to remove the "either is acceptable" hedge. |
| **ISSUE-069** | Clarified that `hasattr()` is the correct tool: goal is to detect MISSING keys (not value-equals-default). Rewrote detection logic description so Dev understands what they're implementing. |
| **ISSUE-105** | Removed the contradictory "compute before lock" paragraph. Added explicit pseudocode showing full sequence inside lock. Clarified that `_actual_spend` must be assigned to an enclosing-scope local after the lock exits so rollback and log record can use it. |
| **ISSUE-032** | Confirmed env_config has NO circular import risk (only imports `os`, `json`, `pathlib` — zero agent dependencies). Added explicit handling spec for empty or malformed wallet file. |

---

## Overview

This sprint is the Signal Integrity cluster for crypto_15m. These are all correctness fixes — no behavior should be silently wrong after this sprint lands.

The issues fall into three groups:

1. **Infrastructure reliability** — WS reconnect (ISSUE-096), wallet path (ISSUE-032)
2. **Signal computation guards** — Near-zero OI delta (ISSUE-129), weight sum assertion (ISSUE-114), fallback weight warning (ISSUE-069)
3. **Cap accounting accuracy** — Module cap init (ISSUE-104), window cap overcounting (ISSUE-105)

ISSUE-116 (Polymarket ETH alias) is Strategist domain — placeholder section included for sprint batching visibility.

Files touched:
- `agents/ruppert/data_analyst/ws_feed.py` — ISSUE-096
- `agents/ruppert/trader/crypto_client.py` — ISSUE-032
- `agents/ruppert/trader/crypto_15m.py` — ISSUE-129, ISSUE-114, ISSUE-069, ISSUE-105
- `agents/ruppert/strategist/strategy.py` — ISSUE-104
- `agents/ruppert/data_analyst/polymarket_client.py` — ISSUE-116 (Strategist to spec)

---

## ISSUE-096 — WS Reconnect Exponential Backoff

**File:** `agents/ruppert/data_analyst/ws_feed.py`  
**Area:** `run_ws_feed()` reconnect loop

### What the bug is

The WS feed's reconnect loop uses a flat 5-second sleep on every error-based disconnect. Additionally, the timeout-based reconnect path (30s recv silence) has **no sleep at all** — it reconnects immediately on every timeout.

The current `run_ws_feed()` structure in `ws_feed.py` (lines ~826–935) is:

```python
while True:
    try:
        async with websockets.connect(...) as ws:
            _write_heartbeat()  # called immediately after successful connect
            # ... subscribe ...
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        log_activity('[WS Feed] recv timeout (30s silence) — reconnecting')
                        break   # <-- PATH 1: timeout-based reconnect, NO sleep, falls through to outer while True
                    # ... message handling ...
            finally:
                fallback_task.cancel()
                # ...

    except Exception as e:
        print(f'  [WS Feed] Disconnected: {e} — reconnecting in 5s')
        # ...
        await asyncio.sleep(5)   # <-- PATH 2: error-based reconnect, flat 5s sleep

    finally:
        market_cache.persist()
```

**Two reconnect paths exist:**

- **PATH 1 — Timeout disconnect:** `asyncio.TimeoutError` inside the inner `while True` triggers `break`, which exits the inner loop, hits the `finally: fallback_task.cancel()`, then exits the `async with ws:` block cleanly. Execution falls through to `finally: market_cache.persist()` and loops back to the outer `while True:`. **No sleep at all.** If Kalshi goes silent (0 messages for 30s), the feed reconnects immediately with no delay — and will hammer the endpoint at one attempt per ~30s if the silence persists.

- **PATH 2 — Exception disconnect:** Any exception in the outer `try` (including WS protocol errors, auth failures, network drops) hits `except Exception as e:` which sleeps a flat 5 seconds every time, regardless of retry count. A real outage means 12 attempts/minute indefinitely — the pattern that triggers rate-limiting or soft-bans.

Neither path applies backoff.

### What the fix is

Add an exponential backoff variable **outside** the `while True` loop (function scope, not inside the loop body). Both paths — timeout and exception — must apply and advance the backoff. Reset the backoff on successful connection, using `_write_heartbeat()` (which is already called immediately after `async with websockets.connect(...)` succeeds) as the reset anchor.

**Why the variable must live outside `while True`:** Any variable assigned inside the loop body resets to its initial value at the top of every iteration. The backoff counter must accumulate across failed iterations — it can only do that if it lives in the enclosing function scope.

**Why `_write_heartbeat()` is the correct reset anchor:** At that point, `websockets.connect()` has returned successfully (the connection is live). Resetting at "top of while True before connect attempt" would reset before we know whether the previous attempt succeeded, which defeats the purpose.

Pseudocode for the complete fix:

```python
async def run_ws_feed():
    # ... imports, setup ...

    _reconnect_delay = 5    # starts at 5s — OUTSIDE while True
    _reconnect_max   = 60   # caps at 60s  — OUTSIDE while True

    while True:
        try:
            async with websockets.connect(...) as ws:
                # Reset backoff HERE — connection succeeded
                _reconnect_delay = 5
                _write_heartbeat()

                # ... subscribe, fallback_task, bootstrap ...

                try:
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            log_activity('[WS Feed] recv timeout (30s silence) — reconnecting')
                            break  # PATH 1 exit — will sleep via the new logic below

                        # ... message handling ...
                finally:
                    fallback_task.cancel()
                    # ...

            # PATH 1 lands here: clean exit from async with ws: after timeout break
            # Apply backoff before reconnecting
            log_activity(f'[WS Feed] Timeout disconnect — reconnecting in {_reconnect_delay}s')
            await asyncio.sleep(_reconnect_delay)
            _reconnect_delay = min(_reconnect_delay * 2, _reconnect_max)

        except Exception as e:
            # PATH 2: exception-based disconnect
            print(f'  [WS Feed] Disconnected: {e} — reconnecting in {_reconnect_delay}s')
            log_activity(f'[WS Feed] Disconnected: {e}')
            try:
                await position_tracker.recovery_poll_positions()
            except Exception as re:
                logger.warning('[WS Feed] Recovery poll failed: %s', re)
            await asyncio.sleep(_reconnect_delay)
            _reconnect_delay = min(_reconnect_delay * 2, _reconnect_max)

        finally:
            market_cache.persist()
```

**Important structural note:** The "PATH 1 lands here" sleep block (after `async with ws:` exits cleanly) must be placed inside the outer `try:` block but outside the `async with ws:` block. This placement ensures it runs on timeout-based clean exit but NOT when an exception fires (the exception path is handled by `except Exception as e:` separately). Dev must verify the placement doesn't conflict with the existing `finally: market_cache.persist()` — that `finally` runs regardless of which path exits the outer `try`, which is correct.

### Behavior change after fix

Before: timeout disconnect → immediate retry, no sleep. Exception disconnect → flat 5s every time.  
After: both paths use exponential backoff: 5s → 10s → 20s → 60s cap. Resets to 5s on successful reconnect.

**Impact on trading:** Near-zero. The recovery poll (`recovery_poll_positions()`) fires on exception-based disconnects (PATH 2) to catch missed moves. The timeout path (PATH 1) means Kalshi went silent — during silence there are no live moves to catch anyway. The backoff only affects reconnect aggressiveness, not position monitoring.

### What could go wrong

- **Longer outage gaps.** 60s cap is standard practice. The recovery poll (already present for PATH 2) is the safety net during gap.
- **Reset placement.** `_reconnect_delay = 5` is reset at `_write_heartbeat()` inside `async with ws:`. If `_write_heartbeat()` is moved or removed in future refactors, the reset should stay pinned to the line immediately after `async with websockets.connect(...)` succeeds — not at the top of `while True`.

### Scope

`agents/ruppert/data_analyst/ws_feed.py`. Reconnect logic in `run_ws_feed()` only. No other files touched.

---

## ISSUE-032 — Smart Money Wallets Path Fix

**File:** `agents/ruppert/trader/crypto_client.py`  
**Area:** `_load_wallets()` / `_WALLETS_FILE` constant

### What the bug is

`crypto_client.py` defines the wallet file path as:

```python
_WALLETS_FILE = Path(__file__).parent / 'logs' / 'smart_money_wallets.json'
```

This resolves to `agents/ruppert/trader/logs/smart_money_wallets.json`.

But `wallet_updater.py` writes the live wallet list to `environments/demo/logs/smart_money_wallets.json` — which is where `env_config.get_paths()['logs']` points.

These are two different directories. The `trader/logs/` file does not exist (confirmed). So `_WALLETS_FILE.exists()` returns False on every call. `_load_wallets()` always falls through to the 3-wallet hardcoded stub (`TOP_TRADER_WALLETS`). The live wallet list from `wallet_updater.py` is silently ignored every time.

### Circular import analysis (confirmed safe)

**env_config.py imports only:** `os`, `json`, `pathlib.Path` — standard library only. It does not import anything from `agents.ruppert.*` or from `crypto_client.py`. There is zero circular import risk. Adding `from agents.ruppert.env_config import get_paths` as a module-level import in `crypto_client.py` is safe.

### What the fix is

Change `_WALLETS_FILE` to use `env_config.get_paths()['logs']`:

```python
from agents.ruppert.env_config import get_paths as _env_get_paths
_WALLETS_FILE = _env_get_paths()['logs'] / 'smart_money_wallets.json'
```

This is the same pattern used in `crypto_15m.py` and `ws_feed.py` for all other log files. It ensures the wallet path resolves to `environments/demo/logs/smart_money_wallets.json`, which is where `wallet_updater.py` writes.

If `env_config` is already imported elsewhere in `crypto_client.py`, reuse that import. If not, add it as a module-level import (not a lazy import inside the function — the circular dependency risk was investigated and does not exist).

### Empty or malformed wallet file handling

The existing `_load_wallets()` code handles malformed files via a `try/except` that falls back to the hardcoded stub. Dev must confirm it also handles:

1. **Empty file** (`smart_money_wallets.json` exists but is 0 bytes or contains `{}`): `json.loads('')` raises `json.JSONDecodeError`, which is caught by the existing `except Exception as e:` and falls back to the stub. No change needed — this case already works.

2. **Valid JSON but missing `wallets` key** (e.g., `{"updated_at": "..."}` with no `wallets` field): `data.get('wallets', [])` returns `[]`, the `if raw and isinstance(raw, list):` guard fails (empty list is falsy), so the function falls through to the stub fallback. No change needed — this case already works.

3. **Spec requirement:** Dev should add a `logger.warning` for the empty/missing-wallets case so it's visible in logs:

```python
raw = data.get('wallets', [])
if raw and isinstance(raw, list):
    # ... success path ...
else:
    logger.warning(
        '_load_wallets: wallet file exists but contains no wallets '
        '(key missing or empty list) — using hardcoded fallback'
    )
    # falls through to stub
```

### Behavior change after fix

Before: always uses 3-wallet hardcoded stub, regardless of what `wallet_updater.py` produced.  
After: uses the live wallet list (currently ~top 20 Polymarket leaderboard wallets). Falls back to stub only if the file is missing, empty, or malformed. The `wallet_source` field in `get_polymarket_smart_money()` result correctly reports `'dynamic'` when the live file is present.

**Impact on trading:** The smart money signal quality improves with the full live wallet list. With only 3 wallets, directional consensus coverage is minimal. The direction of the change is unambiguously correct.

### What could go wrong

- **`wallet_updater.py` hasn't run.** If `wallet_updater.py` hasn't been run recently, `smart_money_wallets.json` may be stale (>25h old). `_load_wallets()` already logs a warning for this case — no change needed. The staleness check is already correct.

### Scope

`agents/ruppert/trader/crypto_client.py`. Change `_WALLETS_FILE` assignment, add `env_config` import, add `logger.warning` for empty/missing wallets case. No other files touched.

---

## ISSUE-129 — Near-Zero OI Delta Guard

**File:** `agents/ruppert/trader/crypto_15m.py`  
**Function:** `fetch_open_interest_delta()`

### What the bug is

The OI delta function computes:

```python
if prev_oi is _CACHE_MISS or prev_oi == 0:
    return {'oi_z': 0.0, 'stale': False, 'raw': 0.0, 'ts': last_ts}

oi_delta_pct = (curr_oi - prev_oi) / prev_oi
```

The guard `prev_oi == 0` catches exact zero, but not near-zero values. If `prev_oi` is, say, `1e-8` (a valid float returned by OKX for a near-dormant market or at contract rollover), the guard does not fire. Then:

```
oi_delta_pct = (curr_oi - 1e-8) / 1e-8
```

If `curr_oi` is anything realistic (e.g., 500 contracts), this produces a delta on the order of 5×10^10. Even after being clipped by `_z_score()` to [-2, 2], the rolling window now contains an astronomically large raw value, which corrupts the window's mean and stdev for multiple subsequent evals. The rolling deque takes `ROLLING_WINDOW` ticks to flush the corrupt entry.

Note: `_z_score()` already guards `sd < 1e-10` → returns 0.0. So the immediate z-score output is safe. But the corrupt raw value contaminates `_rolling_oi` for subsequent windows, shifting the mean and inflating/deflating z-scores on legitimate data for the next several minutes.

### What the fix is

Extend the guard to cover near-zero values:

```python
if prev_oi is _CACHE_MISS or prev_oi < 1e-6:
    return {'oi_z': 0.0, 'stale': False, 'raw': 0.0, 'ts': last_ts}
```

Change `prev_oi == 0` to `prev_oi < 1e-6`. This catches both exact zero and any sub-meaningful OI reading (< 1 millionth of a contract, which is effectively noise).

1e-6 is a safe threshold — realistic OI readings for KXBTC/KXETH are in the hundreds to thousands of contracts. A reading below 1e-6 is either a data artifact or a brand-new market with no positions.

No change to `_z_score()` itself — the existing `sd < 1e-10` guard there is already correct. This fix is only in the OI delta guard.

### Behavior change after fix

Before: `prev_oi` near-zero (but not exactly zero) passes through, producing extreme delta that corrupts the rolling window.  
After: any `prev_oi < 1e-6` returns `oi_z: 0.0` cleanly, no rolling window contamination.

**Impact on trading:** OI signal is more reliable on markets with sparse early-window data or at contract rollover. The effect is most visible in the first few ticks of a new 15m window. Practically: slightly fewer phantom OI signals at window open.

### What could go wrong

- **Threshold too aggressive.** 1e-6 is extremely conservative — it will only guard near-zero values. Any realistic OI reading will pass through. This is not a risk.
- **curr_oi should also be checked.** If `curr_oi` is near-zero and `prev_oi` is large, `oi_delta_pct` will be a large negative number — this is legitimate signal (mass OI unwind). No guard needed for `curr_oi` on the denominator side. Only `prev_oi` is the denominator.

### Scope

`agents/ruppert/trader/crypto_15m.py`. One-line change: `prev_oi == 0` → `prev_oi < 1e-6` in `fetch_open_interest_delta()`. No other files touched.

---

## ISSUE-114 — Signal Weights Sum Assertion at Module Load

**File:** `agents/ruppert/trader/crypto_15m.py`  
**Area:** Module-level constants (lines 72–76)

### What the bug is

The signal weights are loaded at module level:

```python
W_TFI  = getattr(config, 'CRYPTO_15M_DIR_W_TFI',  0.42)
W_OBI  = getattr(config, 'CRYPTO_15M_DIR_W_OBI',  0.25)
W_MACD = getattr(config, 'CRYPTO_15M_DIR_W_MACD', 0.15)
W_OI   = getattr(config, 'CRYPTO_15M_DIR_W_OI',   0.18)
```

The defaults sum to 1.00 (0.42 + 0.25 + 0.15 + 0.18 = 1.00). But there is no validation. If a config override sets these to values that don't sum to 1.0 — e.g., a typo that sets `W_TFI = 0.50` without adjusting the others — the composite score silently scales:

```python
raw_score = W_TFI * tfi_z + W_OBI * obi_z + W_MACD * macd_z + W_OI * oi_z
```

If weights sum to 1.10, every raw_score is 10% inflated. This shifts `P_directional` and edge calculations without any log entry or warning. The effect is small but directionally systematic — every signal in that session is biased by the weight sum error.

### What the fix is

Add a `raise ValueError` guard immediately after the weight definitions. **Do not use `assert`** — Python's `-O` (optimize) flag silently disables all `assert` statements, which would remove the guard entirely if the process is ever launched with `-O`. A `raise ValueError` is immune to this flag.

```python
_weights_sum = W_TFI + W_OBI + W_MACD + W_OI
if abs(_weights_sum - 1.0) >= 1e-6:
    raise ValueError(
        f"CRYPTO_15M signal weights must sum to 1.0, got {_weights_sum:.6f} "
        f"(TFI={W_TFI}, OBI={W_OBI}, MACD={W_MACD}, OI={W_OI})"
    )
```

The error message includes the actual sum so operators can immediately see how far off the config is without reading code. This fires at module import, before any signal computation. If weights are misconfigured, the import fails with a clear, debuggable error.

**Sequencing note:** Apply ISSUE-069 (fallback weight warning) first, then this fix. In the code, the WARNING log line from ISSUE-069 must appear **before** the `raise ValueError` line. This ensures if weights are misconfigured AND a key was missing from config, the WARNING logs first (providing context: "we were using fallback defaults") before the ValueError fires. This sequencing is about code order in the file, not sprint deployment order.

### Behavior change after fix

Before: misconfigured weights produce silently biased composite scores.  
After: misconfigured weights cause an immediate `ValueError` at module load, preventing any trades with bad weights.

**Impact on trading:** Zero impact on any session where weights sum correctly. Fail-fast on misconfiguration is strictly better than silent bias.

### What could go wrong

- **Floating point precision.** Use `1e-6` tolerance, not exact equality. 0.42 + 0.25 + 0.15 + 0.18 in IEEE 754 may not be exactly 1.0. The 1e-6 tolerance handles this without false positives.
- **Import failure halts 15m evals.** If `ValueError` fires, `crypto_15m.py` fails to import. The `_safe_eval_15m()` wrapper in `ws_feed.py` will catch the `ImportError` and log it. All 15m evaluations for that session will be skipped. This is the intended behavior — misconfigured weights should halt trading, not bias it silently.

### Scope

`agents/ruppert/trader/crypto_15m.py`. Add 4–5 lines after the `W_OI` definition. No other files touched.

---

## ISSUE-069 — Log WARNING When Config Fallback Weights Are Used

**File:** `agents/ruppert/trader/crypto_15m.py`  
**Area:** Module-level weight loading (lines 72–76)

### What the bug is

The weights are loaded with `getattr()` fallbacks:

```python
W_TFI  = getattr(config, 'CRYPTO_15M_DIR_W_TFI',  0.42)
```

If `config` lacks the attribute — e.g., because the config import failed silently, or the key was accidentally removed — `W_TFI` silently takes the hardcoded fallback value `0.42`. No log entry is written. The process continues, trading on Phase 1 defaults without anyone knowing.

The Phase 1 defaults (0.42/0.25/0.15/0.18) may not match current tuning. If they diverge from production config, every composite score in the session is computed on stale weights. This is silent and directionally wrong.

### What the fix is

The goal is to detect when `getattr()` falls back to the default because the **key is MISSING from config** — not to detect whether the loaded value happens to equal the default. `hasattr(config, 'KEY')` returns `False` exactly when `getattr(config, 'KEY', default)` would use its default argument. This is the correct tool for the job.

Implementation:

```python
_W_TFI_DEFAULT  = 0.42
_W_OBI_DEFAULT  = 0.25
_W_MACD_DEFAULT = 0.15
_W_OI_DEFAULT   = 0.18

W_TFI  = getattr(config, 'CRYPTO_15M_DIR_W_TFI',  _W_TFI_DEFAULT)
W_OBI  = getattr(config, 'CRYPTO_15M_DIR_W_OBI',  _W_OBI_DEFAULT)
W_MACD = getattr(config, 'CRYPTO_15M_DIR_W_MACD', _W_MACD_DEFAULT)
W_OI   = getattr(config, 'CRYPTO_15M_DIR_W_OI',   _W_OI_DEFAULT)

# Detect which keys are MISSING from config (getattr fell back to default)
_missing_weight_keys = [
    key for key, present in [
        ('CRYPTO_15M_DIR_W_TFI',  hasattr(config, 'CRYPTO_15M_DIR_W_TFI')),
        ('CRYPTO_15M_DIR_W_OBI',  hasattr(config, 'CRYPTO_15M_DIR_W_OBI')),
        ('CRYPTO_15M_DIR_W_MACD', hasattr(config, 'CRYPTO_15M_DIR_W_MACD')),
        ('CRYPTO_15M_DIR_W_OI',   hasattr(config, 'CRYPTO_15M_DIR_W_OI')),
    ] if not present
]
if _missing_weight_keys:
    logger.warning(
        'crypto_15m: signal weight config keys missing: %s. '
        'Using fallback defaults: TFI=%.2f OBI=%.2f MACD=%.2f OI=%.2f',
        ', '.join(_missing_weight_keys),
        W_TFI, W_OBI, W_MACD, W_OI,
    )
```

**Why `hasattr()` and not value comparison:** We want to know "did we fall back because the key was absent?" — not "does the loaded value happen to match the default?" These are different questions. If someone explicitly sets `CRYPTO_15M_DIR_W_TFI = 0.42` in config (same as default), the key IS present, `hasattr()` returns True, no warning fires — correct, because config is properly configured. If the key is absent, `hasattr()` returns False, warning fires — correct, because we're flying on fallbacks. Value comparison would produce false positives (warn when key is present but value equals default, which is fine) and would not help diagnose the actual problem (missing key).

**Sequencing:** This WARNING log must appear **before** the ISSUE-114 `raise ValueError` in the file. If weights are misconfigured AND keys were missing, operators see "using fallback defaults" in the log before the ValueError, giving them the full context.

**Note on module-load logging:** The WARNING fires during module import. If the caller hasn't configured Python logging handlers yet (e.g., `logging.basicConfig()` runs in `if __name__ == '__main__':` after all imports), this WARNING may be silently discarded. This is a known Python logging gotcha for module-load warnings. The WARNING will appear in logs in any normal run where `logging.basicConfig()` is called before the first import (or if the process uses a logging config file). Dev should verify the WARNING appears in startup logs after implementation.

### Behavior change after fix

Before: config fallback used silently, no log entry.  
After: WARNING logged at module load when any weight key is MISSING from config. Warning message names the specific missing keys and shows the fallback values being used.

**Impact on trading:** None — the WARNING is informational only. The weights loaded are identical to before. The only change is visibility.

### What could go wrong

- **False positives on fresh deploys.** If config keys genuinely don't exist yet (fresh environment, not yet configured), this WARNING fires on every module load. That is acceptable — the WARNING is correct in that case. Silence was the wrong behavior.
- **logger not initialized.** See note above on module-load logging. Dev should verify WARNING appears in actual startup output.

### Scope

`agents/ruppert/trader/crypto_15m.py`. Modify the weight-loading block (lines 72–76). Add ~15 lines. No other files touched.

---

## ISSUE-116 — Polymarket ETH Alias Word-Boundary Fix

**File:** `agents/ruppert/data_analyst/polymarket_client.py`  
**Owner:** Strategist

**Placeholder — Strategist to spec ISSUE-116 separately.**

Brief context for sprint visibility: the Polymarket ETH alias matching uses a substring search that can match "ETH" inside tokens like "TEETH" or "BETH". The fix is to add word-boundary guards (e.g., `\bETH\b` regex or exact token match). This affects `get_crypto_consensus()` which is called by `crypto_15m.py` for the Polymarket bias nudge. Once Strategist's spec is written and Dev implements, the crypto_15m Polymarket integration benefits automatically — no changes needed in crypto_15m.py itself.

---

## ISSUE-104 — Initialize `_module_cap_missing` Before the `if` Block

**File:** `agents/ruppert/strategist/strategy.py`  
**Function:** `should_enter()`

### What the bug is

The current code in `should_enter()`:

```python
if module is not None:
    _module_key = module.upper() + '_DAILY_CAP_PCT'
    _module_cap = getattr(config, _module_key, None)
    _module_cap_missing = _module_cap is None      # assigned INSIDE the if block
    if not _module_cap_missing:
        ...

# ... later ...
if module is not None and _module_cap_missing:    # read OUTSIDE the if block
    _result['warning'] = f'no_daily_cap_config_for_{module} ...'
```

`_module_cap_missing` is assigned only inside `if module is not None:`. It is read later at `if module is not None and _module_cap_missing:`. Due to Python short-circuit evaluation, this is technically safe: when `module is None`, the second condition `_module_cap_missing` is never evaluated, so no NameError fires.

However, the code reads as though `_module_cap_missing` might be uninitialized, and any static analysis tool or linter will flag it as a potential NameError. The intent is unclear to future readers.

### What the fix is

Initialize `_module_cap_missing = False` before the `if module is not None:` block:

```python
_module_cap_missing = False   # default: cap config is present (module is None path)
if module is not None:
    _module_key = module.upper() + '_DAILY_CAP_PCT'
    _module_cap = getattr(config, _module_key, None)
    _module_cap_missing = _module_cap is None
    if not _module_cap_missing:
        ...
```

With this initialization, the later `if module is not None and _module_cap_missing:` is unambiguously correct: `_module_cap_missing` is always defined, and its value is always accurate.

**Note:** This is a defensive hygiene fix, not a functional bug. Python short-circuit evaluation already prevents the NameError. The fix is purely for code clarity and linter compliance.

### Behavior change after fix

None. Identical runtime behavior. `_module_cap_missing` is `False` in the `module is None` path both before and after.

### What could go wrong

Nothing. The initialization adds a default value that is never consulted in the `module is None` path (same as before, due to short-circuit). The only risk is if someone in the future removes the `module is not None and` prefix from the later check — but with the explicit initialization, that would still be safe (it would just always be False when module is None).

### Scope

`agents/ruppert/strategist/strategy.py`. One line added before the `if module is not None:` block. No other files touched.

---

## ISSUE-105 — Use Post-Trim Actual Amount in Window Cap Reservation

**File:** `agents/ruppert/trader/crypto_15m.py`  
**Function:** `evaluate_crypto_15m_entry()`

### What the bug is

Inside the `_window_lock` block, after trimming `position_usd` to fit the window cap, the reservation is made:

```python
# Reserve capacity atomically
_window_exposure[win_key] = _window_exposure.get(win_key, 0.0) + position_usd
_daily_wager += position_usd
```

Then, outside the lock:

```python
contracts = max(1, int(position_usd / (entry_price / 100.0)))
```

`contracts` is floored at 1 via `max(1, ...)`. The actual dollars spent is:

```
actual_spend = contracts * (entry_price / 100.0)
```

When `position_usd` is trimmed to a small value (e.g., window cap had $3 remaining), the contract math might produce a different spend:

- `position_usd = 3.00`, `entry_price = 40`
- `contracts = max(1, int(3.00 / 0.40)) = max(1, 7) = 7`
- `actual_spend = 7 * 0.40 = $2.80`
- Counter charged: $3.00. Actual deployed: $2.80.

Over 5 assets × 96 windows/day, these small discrepancies compound. The `_window_exposure` counter systematically overstates actual deployment, leaving available window capacity unclaimed.

### What the fix is

Move contract computation to **inside the lock, after all trim logic**, using the final post-trim `position_usd`. Use the resulting `actual_spend` for the reservation. Assign `actual_spend` to an enclosing-scope local after the lock exits so it's available to the rollback path and log record below.

**Explicit pseudocode — implement exactly this sequence:**

```python
# Before the lock: declare variable that will hold actual_spend after lock exits
actual_spend = None   # will be set inside lock

with _window_lock:
    # Step 1: All existing trim logic runs here, position_usd may be reduced
    #   (window cap check, daily wager check, etc. — unchanged)

    if not _skip_reason:
        # Step 2: Compute contracts from FINAL post-trim position_usd
        _contracts = max(1, int(position_usd / (entry_price / 100.0)))

        # Step 3: Compute actual_spend = contracts × entry_price/100
        _actual_spend = _contracts * (entry_price / 100.0)

        # Step 4: Reserve actual_spend (not position_usd)
        _window_exposure[win_key] = _window_exposure.get(win_key, 0.0) + _actual_spend
        _daily_wager += _actual_spend

        # Step 5: Expose to enclosing scope for rollback and log record
        actual_spend = _actual_spend
        contracts = _contracts  # replaces the outside-lock contracts computation

# Outside the lock: use contracts and actual_spend (both set inside lock)
# ... order placement using contracts ...

# On order failure (rollback path):
with _window_lock:
    _window_exposure[win_key] = max(0.0, _window_exposure.get(win_key, 0.0) - actual_spend)
    _daily_wager = max(0.0, _daily_wager - actual_spend)

# In log record:
'size_dollars': round(actual_spend, 2),  # was: round(position_usd, 2)
```

**Why contracts must be computed inside the lock:** The trim logic may reduce `position_usd` (e.g., cap has $3 remaining but we requested $10). If contracts were computed before the lock using the pre-trim `position_usd`, we'd compute the wrong contract count. Computing inside the lock, after trim, guarantees we use the final value.

**Why `actual_spend` must be assigned to enclosing scope:** The rollback path and log record are outside the lock block. Python local variables defined inside a `with` block are accessible in the enclosing function scope after the block exits — but for clarity and correctness, explicitly assign `actual_spend = _actual_spend` inside the lock (so it's set in the function's local namespace before the `with` block exits). The rollback path's second `with _window_lock:` acquisition is safe — it's in a separate code path after the first lock has already been released.

**The existing `contracts` assignment outside the lock must be removed** — it's now computed inside the lock. If it's left in place, it will overwrite the correct value with a potentially stale one.

### Behavior change after fix

Before: window counter charged `position_usd` (pre-contract-floor). Systematically overcounts actual deployment by up to a few cents per trade due to integer rounding.  
After: window counter charged `actual_spend` (contracts × entry_price/100). Accurately reflects capital actually committed.

**Impact on trading:** More remaining window capacity available, especially late in busy windows. Net effect: slightly more trades pass the window cap gate near the cap boundary. `size_dollars` in the log record now matches the actual amount reserved, making `_rehydrate_state()` consistent (both `get_window_exposure()` and `get_daily_wager()` read from `size_dollars` — both will now use the accurate value).

### What could go wrong

- **Contracts computed inside lock means lock is held slightly longer.** The contract math is two integer operations — negligible.
- **`actual_spend` is None if `_skip_reason` is set.** The rollback path should only run if the order was placed (i.e., `_skip_reason` was not set). Verify the rollback code is guarded by the same condition. If `actual_spend` is still `None` at the rollback, it's a logic error — Dev should add an assertion or check.
- **Rehydration consistency.** `_rehydrate_state()` reads `size_dollars` from the trade log for both `get_window_exposure()` and `get_daily_wager()`. After this fix, `size_dollars = round(actual_spend, 2)` means rehydration is accurate. Both counters source from the same field — this is correct and consistent.

### Scope

`agents/ruppert/trader/crypto_15m.py`. Move/modify contract computation and reservation lines inside `evaluate_crypto_15m_entry()`. Update rollback line. Update `size_dollars` in log record. Remove the outside-lock `contracts` assignment that's now handled inside the lock. No other files touched.

---

## Summary

| Issue | File | Change | Risk |
|---|---|---|---|
| ISSUE-096 | `ws_feed.py` | Both reconnect paths (exception AND timeout) get exponential backoff (5→10→20→60s cap). Variable lives outside `while True`. Reset after successful connect. | Low — recovery poll still fires on exception disconnects |
| ISSUE-032 | `crypto_client.py` | `Path(__file__).parent / 'logs'` → `env_config.get_paths()['logs']`. No circular import (confirmed). Add warning for empty/missing wallets case. | Low — fallback stub still works if file missing |
| ISSUE-129 | `crypto_15m.py` | `prev_oi == 0` → `prev_oi < 1e-6` in OI delta guard | Very low — purely expands an existing guard |
| ISSUE-114 | `crypto_15m.py` | Add `raise ValueError` (not `assert`) after W_OI definition. Error message includes actual sum. | Low — only fails on misconfigured weights (intended) |
| ISSUE-069 | `crypto_15m.py` | Log WARNING when weight keys are MISSING from config. Uses `hasattr()` to detect missing keys. WARNING names specific missing keys. | None — informational only |
| ISSUE-116 | `polymarket_client.py` | Strategist to spec separately | N/A |
| ISSUE-104 | `strategy.py` | Initialize `_module_cap_missing = False` before `if module is not None:` | None — pure hygiene |
| ISSUE-105 | `crypto_15m.py` | Compute contracts and actual_spend INSIDE lock after trim. Reserve actual_spend. Assign to enclosing scope for rollback and log record. Update `size_dollars` in log record. | Low — Dev must update reservation, rollback, and log record together |

**Recommended ship order:** ISSUE-069 first (WARNING before ValueError in code), then ISSUE-114 (builds on it), then ISSUE-096, ISSUE-032, ISSUE-129, ISSUE-105 (most complex), ISSUE-104 (trivial, can batch with anything).

---

_Trader sign-off: all specs revised against source. Adversarial review issues addressed. Awaiting David review before Dev starts._
