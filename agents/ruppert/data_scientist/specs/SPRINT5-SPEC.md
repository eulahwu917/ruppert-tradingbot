# Sprint 5 Spec — CB Coverage, Timezone, EXIT_GAIN_PCT, NO-Side P&L Fix
**Date:** 2026-04-03  
**Authored by:** DS  
**Issues:** ISSUE-076, ISSUE-047, ISSUE-044, ISSUE-043, ISSUE-042  
**Reviewer:** David (please review before Dev starts)

---

## Overview

5 issues across 3 files:
- `circuit_breaker.py` — ISSUE-076 (file locking), ISSUE-047 (SOL/XRP/DOGE CB coverage)
- `ws_feed.py` + everywhere — ISSUE-044 (timezone: `date.today()`)
- `config.py` + `position_tracker.py` — ISSUE-043 (EXIT_GAIN_PCT inconsistency)
- `position_tracker.py` — ISSUE-042 (NO-side flip removal + DS capital correction)

---

## ISSUE-076 — CB TOCTOU Race (File Lock)

**Problem:** `circuit_breaker.py` reads the state file, modifies it in memory, then writes it back. If two modules do this concurrently (e.g. BTC and ETH both exit the same 15m window at the same time), both read the same old count, both increment, and both write — last write wins, one increment is lost. The breaker may never trip.

**Fix:**

In `circuit_breaker.py`, wrap every read-modify-write in a `portalocker` file lock. Add to imports:

```python
import portalocker
```

Create a new private function `_rw_locked(path, fn)` that:
1. Opens the state file — try `r+` mode first, catch `FileNotFoundError` and fall back to `w+` (cold start when file doesn't exist yet)
2. Acquires an exclusive lock (portalocker.LOCK_EX)
3. Reads the JSON
4. Calls `fn(state)` to modify it
5. Writes the modified state back
6. Releases the lock

Replace the body of `increment_consecutive_losses()` and `reset_consecutive_losses()` to use this pattern. `update_global_state()` also needs the lock since it writes to the `global` key.

`_read_full_state()` (read-only) does NOT need a lock — reads are atomic enough.

**Scope:** `circuit_breaker.py` only  
**Trading behavior change:** None — same logic, now race-safe  
**Risk:** Low. portalocker is already a dependency (used in logger.py)

---

## ISSUE-047 — CB Only Covers BTC + ETH

**Problem:** The CB key lookup in `crypto_15m.py` uses `_module_name` (e.g. `crypto_dir_15m_btc`) which is per-asset. But after the ISSUE-001 fix (SOL now routes to 15m evaluator), SOL/XRP/DOGE are now live. Their CB counters ARE tracked in `_ALL_CRYPTO_15M_MODULES` and `_default_module_state` already defines them. So this is partially working — the state entries exist.

**Root cause:** The check was in `crypto_15m.py` which does look up `_module_name` (which IS per-asset), so CB IS being read per-asset. But confirm this by checking whether `ws_feed.py`'s CB check also uses the per-asset module key.

**Check needed:** In `ws_feed.py` around line 466, confirm `_ws_module` is set to something like `crypto_band_daily_btc` or `crypto_dir_15m_btc` — not a generic key.

Looking at `ws_feed.py` line 358 onwards: `_WS_MODULE_MAP` correctly maps `('BTC', 'between')` → `'crypto_band_daily_btc'` etc. And `crypto_15m.py` uses `_module_name` which is derived per-asset. So the CB state keys ARE per-asset.

**Actual fix needed:** Confirm that `_ALL_CRYPTO_15M_MODULES` in `circuit_breaker.py` already contains all 5 assets (it does: `crypto_dir_15m_btc/eth/sol/xrp/doge`). No code change needed to coverage — but we should add explicit logging that names WHICH asset's CB is being checked when it trips, so it's observable.

**What Dev should do:**
1. Confirm that `_ws_module` in the WS feed CB check (line ~469) is per-asset (it should be)
2. Add a log line in `circuit_breaker.py`'s `increment_consecutive_losses()` that says which asset crossed what threshold when it crosses `CRYPTO_15M_CIRCUIT_BREAKER_N` — currently the log just says the count, not if it's a trip
3. No functional change needed if the per-asset key lookup is confirmed correct

**If per-asset lookup is NOT correct in ws_feed.py** (e.g. `_ws_module` is generic): fix the module key derivation to be per-asset before the CB check.

**Scope:** `circuit_breaker.py` (logging only), possibly `ws_feed.py` if key is wrong  
**Risk:** Very low

---

## ISSUE-044 — Timezone Inconsistency: `date.today()` and `datetime.now()`

**Problem:** `date.today()` returns the local OS date. On David's Windows machine (PDT, UTC-7), this is fine most of the time — but between midnight UTC (5pm PDT) and midnight PDT (midnight local), `date.today()` in UTC-aware code gives the wrong date. Specifically:
- CB resets: `circuit_breaker.py` uses `_today_pdt()` correctly already (✅)
- `ws_feed.py` line 563: `opp['date'] = str(date.today())` — logs today's date in the trade record, used for CB lookups. If this fires at 5:01pm PDT, local `date.today()` = Apr 3 but the trade settles on Apr 3 UTC date = Apr 4. Minor but real.
- `ws_feed.py` line 73: `datetime.now().strftime(...)` — just a logging timestamp, cosmetic only
- `ws_feed.py` line 943: `datetime.now().isoformat()` — heartbeat timestamp, cosmetic

**Fix — targeted, not a full rewrite:**

The only functionally important instance is the trade record `date` field. It should match the log file name (which is also `date.today()` elsewhere). This is a cosmetic issue in practice since we're in PDT and the system's local time IS PDT (David's machine is in LA). The CB already uses `_today_pdt()`.

**What Dev should do:**
1. In `ws_feed.py`, create a tiny helper at the top: `def _today_pdt(): return datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%Y-%m-%d')`
2. Replace `str(date.today())` on line 563 with `_today_pdt()`
3. Leave `datetime.now()` on lines 73 and 943 alone — those are cosmetic log timestamps
4. In `circuit_breaker.py`: already uses `_today_pdt()` correctly — no change needed
5. In `position_tracker.py`: uses `str(date.today())` in a few places for trade record dates — replace with `_today_pdt()` equivalent (import pytz and define same helper)

**Files:** `ws_feed.py`, `position_tracker.py`  
**Risk:** Low. This only matters 7 hours/day (5pm–midnight PDT) and the system is already on local PDT time

---

## ISSUE-043 — EXIT_GAIN_PCT Inconsistency (0.70 vs 0.90)

**Problem:** `config.py` line 374 defines `EXIT_GAIN_PCT = 0.90`. But `position_tracker.py` line 41 has:
```python
EXIT_GAIN_PCT = getattr(config, 'EXIT_GAIN_PCT', 0.70)
```
The fallback default of 0.70 is hardcoded. If config import fails (or config is missing the key), position_tracker silently uses the old 0.70. Any position added during that window exits 20% earlier than intended.

**Fix:**

In `position_tracker.py` line 41, remove the `0.70` fallback and instead fail explicitly:

```python
EXIT_GAIN_PCT = getattr(config, 'EXIT_GAIN_PCT', None)
if EXIT_GAIN_PCT is None:
    raise ImportError('[position_tracker] EXIT_GAIN_PCT not found in config — check config.py')
```

This ensures a misconfigured system fails loudly at startup, not silently at exit time.

**Files:** `position_tracker.py`  
**Trading behavior change:** None in normal operation. Config is correct (0.90). Only affects misconfigured startup.  
**Risk:** Very low

---

## ISSUE-042 — NO-Side Entry Price Flip (the $7,863.61 bug)

This is the most complex fix. Two parts: code patch + data correction.

### Part A: Code Patch

**Problem:** In `position_tracker.add_position()` (lines 243–245):
```python
if side == 'no' and entry_price < 50:
    entry_price = 100 - entry_price
```

This was added to handle a case where callers passed YES price for NO-side entries. But the 15m evaluator (`crypto_15m.py`) already passes the CORRECT NO price. So this flip is double-flipping it.

For example: a NO at 3c (YES at 97c) → `crypto_15m.py` passes `entry_price=3` → flip converts it to `97` → stored as 97c → all stop math and P&L use 97c as the entry cost, wildly wrong.

**What Dev should do:**

1. In `position_tracker.py` `add_position()`, **remove the NO-side flip entirely**:
   - Delete lines 238–245 (the `size_dollars` pre-flip calculation AND the flip itself)
   - Keep `size_dollars` computation as: `size_dollars = round(entry_price * quantity / 100, 2)` (no pre/post distinction needed once flip is gone)

2. In `_load()` (the startup migration block, lines ~162–175), the migration code flips legacy positions with `entry_price < 50` to `100 - entry_price`. **This migration is now WRONG** — it's trying to fix the old flip, but we're removing the flip. Remove this migration block entirely. Any positions in the tracker from before this fix are already cleaned up (trading was halted).

3. The `normalize_entry_price()` function in `logger.py` (line 478) is a separate function used during log auditing — leave it alone, it doesn't affect live trading.

4. Check the stop-loss threshold code for NO positions in `check_exits()`. The Design D stops compare `yes_bid < entry_price * threshold_pct`. After this fix, `entry_price` for a NO at 3c will be `3` (correct NO price). A 20% catastrophic stop would fire at `yes_bid < 3 * 0.20 = 0.6c` — effectively never (yes_bid is an integer ≥ 0). This is correct behavior for NO positions: when you buy NO at 3c, the YES price going up hurts you, but "catastrophic" means the NO price goes to near-zero. The existing stop-loss for NO-side goes through the threshold checks (`compare='lte'`) at yes_bid ≤ 5c, which is correct. The Design D Tier 1/2/3 stops (which compare against entry_price) are YES-side logic and **should be gated to YES positions only**. **Add a guard:**
   ```python
   if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and side == 'yes':
   ```
   (add `and side == 'yes'` to the Design D stop guard)

**Additional required in same commit (Trader review):**
- The flip removal and migration block removal MUST be in one atomic commit. If the flip is removed but the migration block survives, any position with `entry_price=3` will be re-flipped to `97` on the next restart.
- Clean up stale comments in `execute_exit()` and `check_expired_positions()` that say "entry_price is unreliable due to NO-side flip" — after this fix those comments are wrong.

**Follow-up (non-blocking, track separately):** `synthesizer.py` open P&L formula for NO positions assumes old flipped storage convention — will show inverted live P&L on dashboard after fix. Cosmetic only, does not affect capital. Fix in same commit or as a separate tracked issue.

**Scope:** `position_tracker.py`  
**Risk:** Medium — removing the flip changes stop math for all future NO-side 15m entries. QA must verify that a NO position at 3c now stores entry_price=3 and that the exit thresholds compute correctly.

### Part B: DS Data Correction

After Dev commits the code fix and QA verifies:

DS will:
1. Insert 115 `exit_correction` records into `logs/trades/trades_2026-04-02.jsonl` and `logs/trades/trades_2026-04-03.jsonl`
2. Each correction record format:
   ```json
   {
     "trade_id": "<uuid>",
     "timestamp": "<now>",
     "date": "<trade_date>",
     "ticker": "<ticker>",
     "side": "no",
     "action": "exit_correction",
     "source": "ds_no_side_audit_2026-04-03",
     "module": "<module>",
     "pnl": <correct_pnl - logged_pnl>,
     "pnl_correction": <correct_pnl - logged_pnl>,
     "note": "ISSUE-042 NO-side flip correction: actual_ep=Xc, stored_ep=Yc"
   }
   ```
   **Note:** `action` must be `"exit_correction"` (not `"pnl_correction"`) — `compute_closed_pnl_from_logs()` only reads `"exit_correction"` records. Using any other action string causes silent no-op.
3. Do NOT insert a deposit to `demo_deposits.jsonl`. The correction records alone are sufficient — adding a deposit would double-count the $7,863.61 (capital = deposits + closed P&L from logs, so both paths would add the same amount).
4. Call `circuit_breaker.update_global_state(capital)` after all records are written — the CB state file's cached global net-loss key will be stale after log modification.
5. Run full DS audit to verify capital reconciles to ~$21,010.

**DS needs:** The 115 affected trade records with ticker, module, actual_ep, stored_ep, contracts, logged_pnl, correct_pnl, delta. This data is in `memory/agents/ds-no-side-audit-2026-04-03.md`.

---

## Sequencing

| Step | Who | What |
|------|-----|-------|
| 1 | Dev | ISSUE-076: Add portalocker to circuit_breaker.py read-modify-write ops |
| 2 | QA | Verify no CB race: check that concurrent increment calls don't drop counts |
| 3 | Dev | ISSUE-047: Confirm per-asset CB key in ws_feed.py; add CB trip logging |
| 4 | QA | Verify CB keys are per-asset in ws_feed.py |
| 5 | Dev | ISSUE-044: Add `_today_pdt()` helper to ws_feed.py and position_tracker.py; replace `date.today()` in trade records |
| 6 | QA | Verify date fields in trade records during 5pm–midnight PDT window (can simulate) |
| 7 | Dev | ISSUE-043: Harden EXIT_GAIN_PCT fallback in position_tracker.py |
| 8 | Dev | ISSUE-042 Part A: Remove NO-side flip from add_position(); gate Design D stops to side='yes'; remove legacy migration block |
| 9 | QA | Verify: buy NO at 3c → entry_price stored as 3, not 97. Check exit thresholds compute correctly. Verify stop-loss correctly skips Design D for NO positions. |
| 10 | David | Review QA pass before DS runs data correction |
| 11 | DS | ISSUE-042 Part B: Insert 115 `exit_correction` records (no deposit) |
| 11.5 | DS | Call `circuit_breaker.update_global_state(capital)` to refresh stale CB global state |
| 12 | DS | Full audit — verify capital reconciles to ~$21,010 |

---

## What NOT to Change

- `normalize_entry_price()` in `logger.py` — audit function only, leave alone
- `_update_daily_cb()` and `_recently_exited` in `position_tracker.py` — working correctly
- `check_global_net_loss()` in `circuit_breaker.py` — reads trade log, no race condition (read-only)
- `_today_pdt()` in `circuit_breaker.py` — already correct, don't duplicate it (import from there if needed)
