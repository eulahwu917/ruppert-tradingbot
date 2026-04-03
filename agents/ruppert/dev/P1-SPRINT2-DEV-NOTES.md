# P1 Sprint 2 — Dev Implementation Notes
_Dev agent | 2026-04-03_

---

## Status: All 3 batches implemented — AWAITING QA

---

## Batch 1 — ISSUE-026 + ISSUE-027 (settlement P&L formulas)

### Files changed
- `environments/demo/settlement_checker.py` — `compute_pnl()`
- `agents/ruppert/trader/post_trade_monitor.py` — `check_settlements()`

### Changes made

**settlement_checker.py — compute_pnl():**
- Win branch: `exit_price = 99` → `exit_price = 100`
- Win formula: `(99 - entry_price) * contracts / 100` → `(100 - entry_price) * contracts / 100`
- Loss formula: `-size_dollars` → `-(entry_price * contracts / 100)` (ISSUE-027: asymmetry fix)

**post_trade_monitor.py — check_settlements():**
- Both win branches (side==yes win, side==no win): `exit_price = 99` → `exit_price = 100`
- Both win formulas: `(99 - entry_price) * contracts / 100` → `(100 - entry_price) * contracts / 100`
- Loss branches: NOT touched (already used correct formula per spec)

### Notes
- Loss branches in post_trade_monitor.py confirmed correct; left untouched as specified.
- No change to loss branch handling in settlement_checker.py beyond the formula fix (ISSUE-027).

---

## Batch 2 — ISSUE-110 (retry on API error)

### Files changed
- `environments/demo/settlement_checker.py` — `check_settlements()`
- `agents/ruppert/trader/post_trade_monitor.py` — `check_settlements()` + import

### Changes made

**settlement_checker.py:**
- Replaced bare `try/except/continue` on `client.get_market()` with 3-attempt retry loop
- Delays: attempt 0 fail → wait 1s; attempt 1 fail → wait 2s; attempt 2 fail → no sleep, skip
- `error_count` incremented only on final failure (consistent with prior behavior)
- `if market is None: continue` guard added after loop

**post_trade_monitor.py:**
- Added `import time` at top (was missing — would have caused NameError on retry)
- Same 3-attempt retry loop with 1s/2s delays
- No `error_count` in post_trade_monitor.py — omitted per spec
- `if market is None: continue` guard added after loop

### Delay sequence verification
- `wait = 2 ** attempt` with `if attempt < MAX_RETRIES - 1` check:
  - attempt=0: wait=1s ✓
  - attempt=1: wait=2s ✓
  - attempt=2: no sleep (condition false) ✓
- Matches spec: "no sleep after final attempt"

---

## Batch 3 — ISSUE-030 + ISSUE-102

### Files changed
- `environments/demo/ruppert_cycle.py` — `run_position_check()`
- `agents/ruppert/trader/post_trade_monitor.py` — `run_monitor()` auto-exit block
- `agents/ruppert/data_scientist/data_agent.py` — `TICKER_MODULE_MAP` + `_cap_map`

### ISSUE-030 changes

**ruppert_cycle.py — run_position_check():**
- Added `'pnl': pnl` to the `opp` dict in the second loop (execution loop over `actions_taken`)
- `pnl` is the 6th tuple element unpacked as `for action, ticker, side, price, contracts, pnl in actions_taken`
- Covers both dry_run and live branches (shared dict)

**post_trade_monitor.py — run_monitor() auto-exit block:**
- Used **Option B** (update dict after computation as separate line)
- Added `exit_opp['pnl'] = exit_pnl` on the line immediately after `exit_pnl` is computed
- This avoids NameError — `exit_pnl` is defined before it's referenced
- `exit_opp` dict literal left intact (no ordering change needed)

### ISSUE-102 changes

**data_agent.py — TICKER_MODULE_MAP:**
- Added `'KXXRPD': 'crypto_threshold_daily_xrp'`
- Added `'KXDOGED': 'crypto_threshold_daily_doge'`
- Inserted in the threshold daily section, BEFORE the base prefixes (KXXRP, KXDOGE)
- Longest-prefix-first sort handles ordering automatically (KXXRPD=6 chars > KXXRP=5 chars)

**data_agent.py — _cap_map:**
- Added `'crypto_threshold_daily_xrp': 'CRYPTO_1H_DIR_DAILY_CAP_PCT'`
- Added `'crypto_threshold_daily_doge': 'CRYPTO_1H_DIR_DAILY_CAP_PCT'`
- Same cap key as btc/eth/sol threshold daily entries per spec

---

## QA Self-Test Results

```
python environments/demo/audit/qa_self_test.py
PASS — 33/33 checks passed

python environments/demo/audit/config_audit.py
PASS WITH WARNINGS — 6 warnings (all pre-existing Task Scheduler state warnings, not related to this sprint)
```

---

## Flags / Contradictions
None. Spec was clear on all edge cases.

---

## Notes for QA

1. **Batch 1**: Verify settlement_checker.py win records show `exit_price=100` and correct pnl. Verify loss records no longer use `-size_dollars`. Verify post_trade_monitor.py loss branches unchanged.
2. **Batch 2**: Mock API failures to confirm retry fires with 1s, 2s delays (no 4s). Confirm `time` import is at line 16 of post_trade_monitor.py.
3. **Batch 3 ISSUE-030**: Trigger auto-exit in dry-run, confirm `pnl` field present in logged record. In post_trade_monitor.py, `exit_opp['pnl']` is set at the line after `exit_pnl` is computed — no NameError possible.
4. **Batch 3 ISSUE-102**: Confirm KXXRPD → `crypto_threshold_daily_xrp`, KXDOGED → `crypto_threshold_daily_doge`. Confirm KXXRP (no D) still → `crypto_band_daily_xrp`. Confirm `get_daily_cap_utilization()` returns a cap for both new modules.
5. **DS note**: After deploy, run `compute_closed_pnl_from_logs()` before/after fresh exits to quantify ISSUE-030 impact. Check XRP/DOGE threshold daily exposure before deploy (ISSUE-102 cap now enforced — possible first-run breach flag).
