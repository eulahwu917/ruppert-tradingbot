# QA Handoff: WS Feed Circuit Breaker Gate
**Date:** 2026-04-02  
**Authored by:** Dev  
**Status:** Awaiting QA verification — DO NOT commit until QA passes

---

## What Changed

**File:** `agents/ruppert/data_analyst/ws_feed.py`

**Change 1 — Import (line 49):**
```python
import agents.ruppert.trader.circuit_breaker as circuit_breaker
```

**Change 2 — CB gate in `evaluate_crypto_entry()` (after daily cap check, before order placement):**
```python
# ── Circuit breaker gate (per-module) ────────────────────────────────────────
try:
    _cb_n = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_N',
                    getattr(config, 'CRYPTO_1H_CIRCUIT_BREAKER_N', 3))
    _cb_advisory = getattr(config, 'CRYPTO_DAILY_CIRCUIT_BREAKER_ADVISORY', False)
    _cb_losses = circuit_breaker.get_consecutive_losses(_ws_module)
    if _cb_losses >= _cb_n:
        if _cb_advisory:
            logger.info('[WS-CRYPTO] CB advisory: ...')
        else:
            logger.warning('[WS-CRYPTO] CB TRIPPED: ... — entry blocked')
            return
except Exception as _cb_err:
    logger.warning('[WS-CRYPTO] CB gate failed for %s: %s', _ws_module, _cb_err)
```

**No other files were modified.**

---

## What to Test

### Test 1: CB tripped → WS entries blocked

**Setup:** Manually set consecutive_losses ≥ threshold for a module in `circuit_breaker_state.json`:
```json
{
  "crypto_threshold_daily_btc": {
    "consecutive_losses": 3,
    "last_window_ts": "2026-04-02T10:00:00",
    "last_window_result": "loss",
    "date": "2026-04-02"
  }
}
```
(Default threshold is `CRYPTO_DAILY_CIRCUIT_BREAKER_N = 3` from config.)

**Action:** Trigger `evaluate_crypto_entry()` for a BTC threshold ticker (e.g., a `KXBTC-26APR02-T87500` tick with valid edge).

**Expected:**
- Log line: `[WS-CRYPTO] CB TRIPPED: 3 consecutive losses for crypto_threshold_daily_btc (threshold=3) — entry blocked`
- No trade logged in `trades_2026-04-02.jsonl`
- No position added to `tracked_positions.json`
- Function returns without placing any order

---

### Test 2: CB not tripped → WS entries proceed normally

**Setup:** Set consecutive_losses = 0 (or < threshold) for the module in state file, or ensure today's date triggers a fresh reset.

**Action:** Trigger `evaluate_crypto_entry()` for a ticker with valid edge (above `CRYPTO_MIN_EDGE_THRESHOLD`).

**Expected:**
- No CB log line
- Entry proceeds through `should_enter()` check
- If `should_enter()` approves: trade logged, position tracked
- Behavior identical to pre-patch baseline

---

### Test 3: WS exits unaffected by CB

**Setup:** Set CB tripped (consecutive_losses ≥ threshold) for a module.

**Action:** Simulate a price tick on a tracked position that hits the 95c rule or 70% gain threshold.

**Expected:**
- `_safe_check_exits()` fires as normal (it calls `position_tracker.check_exits()`, NOT `evaluate_crypto_entry()`)
- Exit is placed and logged correctly
- CB state has zero effect on exits
- No CB log lines appear during exit flow

---

### Test 4: Per-module isolation

**Setup:** CB tripped for `crypto_threshold_daily_btc` (BTC). ETH module (`crypto_threshold_daily_eth`) has 0 consecutive losses.

**Action:** Trigger price ticks for both BTC and ETH threshold tickers with valid edge.

**Expected:**
- BTC tick: entry blocked by CB
- ETH tick: entry proceeds normally (separate CB counter)

---

### Test 5: CB gate failure is non-fatal

**Setup:** Corrupt `circuit_breaker_state.json` (invalid JSON or unreadable).

**Action:** Trigger `evaluate_crypto_entry()`.

**Expected:**
- Log line: `[WS-CRYPTO] CB gate failed for <module>: <error>`
- Function continues past the gate (fail-open, same behavior as before patch)
- WS feed does NOT crash or restart

**Note:** Fail-open on CB gate exception is intentional — a corrupt state file should not brick the exit monitor.

---

### Test 6: 15m module entries (crypto_15m) — CB NOT applied

**Verify:** The CB gate is ONLY in `evaluate_crypto_entry()` (hourly band path). The `crypto_15m` path goes through `_safe_eval_15m()` → `evaluate_crypto_15m_entry()` (in `crypto_15m.py`), which has its own CB logic. Confirm that the 15m path is unaffected by this patch (no new CB logic was added to `_safe_eval_15m`).

---

## What Was NOT Changed

- `_safe_check_exits()` — exit trigger path. Completely untouched.
- `position_tracker.check_exits()` — exit execution. Completely untouched.
- `_safe_eval_15m()` — 15m crypto entry path. Untouched (has its own CB in `crypto_15m.py`).
- `_fallback_poll_loop()` — REST fallback for missed 15m windows. Untouched.
- Signal computation logic — edge calculation, model_prob, sigma. All untouched.
- `should_enter()` strategy gate — still called after CB gate. Untouched.

---

## How to Run a Manual Smoke Test

```powershell
# 1. Check the import resolves cleanly
cd "C:\Users\David Wu\.openclaw\workspace"
python -c "import agents.ruppert.data_analyst.ws_feed; print('Import OK')"

# 2. Check CB state file
Get-Content "environments\demo\logs\circuit_breaker_state.json"

# 3. Run ws_feed in DRY_RUN mode for 30s and observe logs
# (CEO handles actual restart — Dev does NOT restart)
```

---

## Handoff Notes

- **DO NOT commit** until QA signs off.
- **DO NOT restart ws_feed** — CEO handles restarts.
- The CB check is per-module (same key as crypto_threshold_daily uses: `crypto_threshold_daily_btc/eth`).
- Global net-loss CB (from `check_global_net_loss()`) is NOT applied here — only the per-module consecutive-loss check. This mirrors the scheduled path's step 1b exactly. If global CB is also desired, that's a separate spec.
- The gate fails open (logs warning, continues) if `circuit_breaker_state.json` is unreadable. This prevents a bad state file from silently killing the exit monitor.
