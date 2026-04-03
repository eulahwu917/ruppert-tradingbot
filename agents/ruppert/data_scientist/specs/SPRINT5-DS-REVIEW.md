# Sprint 5 DS Review
**Reviewer:** Data Scientist  
**Date:** 2026-04-03  
**Spec reviewed:** `agents/ruppert/data_scientist/specs/SPRINT5-SPEC.md`  
**Status:** **HOLD — 3 spec changes required before Dev starts**

---

## Executive Summary

ISSUE-076, ISSUE-047, ISSUE-043, and ISSUE-044 are all approved as written. No concerns there.

ISSUE-042 Part A (code fix) is also approved with one clarifying note.

**HOLD is solely for ISSUE-042 Part B (data correction).** The spec as written has two fatal bugs in the correction plan that would either (a) silently apply no P&L correction at all, or (b) double-count the $7,863.61. Both outcomes break capital integrity. Neither should go anywhere near the trade logs without fixing the spec first.

---

## ISSUE-042 Part B — 3 Required Spec Changes

### BUG 1 (Critical): Wrong action type — corrections will be silently ignored

The spec proposes correction records with `action: "pnl_correction"`. This action type **does not exist** in `compute_closed_pnl_from_logs()`. That function (in `logger.py` line 704) only consumes three action types:

```python
if t.get('action') in ('exit', 'settle') and t.get('pnl') is not None:
    total_pnl += float(t['pnl'])
elif t.get('action') == 'exit_correction' and t.get('pnl_correction') is not None:
    total_pnl += float(t['pnl_correction'])
```

A record with `action: "pnl_correction"` hits neither branch. It's dead weight in the log — appended, never read, P&L never updated. Capital stays understated.

**Fix:** Change correction record `action` from `"pnl_correction"` to `"exit_correction"`, matching the established correction schema (see `pnl_correction.py` which already uses this pattern correctly).

### BUG 2 (Critical): Double-counting — both correction records AND deposit cannot coexist

Capital is computed as:

```
capital = sum(demo_deposits.jsonl amounts) + compute_closed_pnl_from_logs()
```

The spec proposes to apply BOTH:
1. 115 correction records added to trade logs → `compute_closed_pnl_from_logs()` picks them up → +$7,863.61 to closed P&L
2. A `+$7,863.61` deposit added to `demo_deposits.jsonl` → +$7,863.61 to base capital

If both are applied, capital will be overcorrected by **+$15,727.22** instead of +$7,863.61. Capital would go from ~$13,146 to ~$28,873 instead of ~$21,010.

**Fix:** Use correction records only. Remove the deposit step entirely. Once `action: "exit_correction"` records with `pnl_correction: <delta>` are correctly appended (Bug 1 fix), `compute_closed_pnl_from_logs()` picks them up automatically and capital reconciles. No deposit required.

The deposit mechanism is for *external capital injections*, not for correcting logged P&L errors.

### BUG 3 (Important): Missing CB state refresh in sequencing

Per DS standing rule (MEMORY.md): **after ANY trade log modification, immediately call `update_global_state(capital)` to refresh the cached global net-loss figure in `circuit_breaker_state.json`.**

Inserting 115 records into the trade logs qualifies. Step 12 says "Full audit — verify capital reconciles" but does not mention CB state refresh. The CB trip decision reads trade logs live so it won't be wrong, but the state file's cached `global` key will show a stale (and now incorrect) net-loss figure until refreshed.

**Fix:** Add a Step 11.5 to the sequencing table:

> **Step 11.5 | DS | Call `update_global_state(capital)` with corrected capital after corrections are inserted. Confirm `circuit_breaker_state.json` `global` key shows updated net-loss figure.**

---

## ISSUE-042 Part A — Code Fix (Approved with Note)

The flip removal and Design D stop guard are correct. One note for Dev:

**synthesizer.py open P&L will break for NO positions after this fix.** The `synthesize_pnl_cache()` function in `synthesizer.py` (line ~83) computes open P&L for NO positions as:

```python
no_entry = 100 - entry_price   # assumes entry_price is stored as YES-equivalent
no_current = 100 - mid_cents
open_pnl += (no_current - no_entry) * contracts / 100
```

Currently this is correct because the flip stores NO at 3c as 97c → `100 - 97 = 3` → correct NO-basis for P&L. After the fix, NO at 3c is stored as 3c → `100 - 3 = 97` → inverted math → dashboard shows losing position as gaining and vice versa.

This doesn't affect capital (capital uses `compute_closed_pnl_from_logs()` for closed P&L only; `synthesize_pnl_cache()` returns but doesn't write pnl_cache.json). But dashboard open P&L display will be wrong for all open NO positions.

**Recommended:** After Part A lands, Dev should fix the NO open P&L formula in `synthesizer.py` to use `entry_price` directly:

```python
if side == 'yes':
    open_pnl += (mid_cents - entry_price) * contracts / 100
else:
    # entry_price is now stored as actual NO cost (e.g., 3c)
    # current NO price = 100 - yes_mid
    no_current = 100 - mid_cents
    open_pnl += (no_current - entry_price) * contracts / 100
```

This can be done in the same Dev commit as Part A or as a follow-up before Step 11. Either is acceptable since it only affects display.

**Tagging this as ISSUE-042 Part A addendum — not a blocker for Part B, but should be tracked.**

---

## ISSUE-044 — `_today_pdt()` Timezone Fix (Approved)

The fix is sufficient. Replacing `str(date.today())` on the trade record `date` field with a PDT-aware helper is the right scope. Lines 73 and 943 (cosmetic timestamps) are correctly left alone.

Minor note: The spec says to define a new `_today_pdt()` in `ws_feed.py` and a separate one in `position_tracker.py`. `circuit_breaker.py` already has `_today_pdt()` and the "What NOT to Change" section itself says to import from there if needed. Duplicate definitions risk drift. Suggest Dev **imports** from `circuit_breaker.py` or extracts to a shared utility rather than defining three copies. Not a blocker, but cleaner.

---

## ISSUE-076, ISSUE-047, ISSUE-043 (All Approved)

- **ISSUE-076 (portalocker):** Correct. `_rw_locked()` pattern is the right approach. `_read_full_state()` correctly excluded.
- **ISSUE-047 (SOL/XRP/DOGE CB):** Correct. The confirm-then-log approach is right. No functional gap if per-asset keys are confirmed correct.
- **ISSUE-043 (EXIT_GAIN_PCT):** Correct. Fail-loud at startup is the right call.

---

## Audit Verification: $7,863.61 Figure

Cross-checked the audit data in `memory/agents/ds-no-side-audit-2026-04-03.md`:

- 115 affected trades (NO-side, ep < 50, WS exit, Apr 2–3)
- Logged P&L sum: $5,064.96
- Correct P&L sum: $12,928.57
- Delta: **$7,863.61** ✓

Breakdown by module:
- BTC: −$3,325.35
- XRP: −$1,865.72
- ETH: −$1,659.04
- DOGE: −$1,013.50

Figure is correct. The audit methodology is sound (scope limited to ep < 50, WS exits only, daily modules confirmed unaffected).

**Correction record count (115) and dollar figure ($7,863.61) are verified.** The only issue is the mechanism for applying them, which is covered by Bugs 1 and 2 above.

---

## Required Spec Changes Before Dev Starts

| # | Section | Change |
|---|---------|--------|
| 1 | ISSUE-042 Part B, correction record format | Change `"action": "pnl_correction"` → `"action": "exit_correction"` |
| 2 | ISSUE-042 Part B, Step 11 | Remove the `+$7,863.61` deposit to `demo_deposits.jsonl`. Correction records alone are sufficient. |
| 3 | Sequencing table | Add Step 11.5: DS calls `update_global_state(capital)` after correction records are inserted, confirms CB state file is refreshed. |

**Optional (not blocking):**
- Add ISSUE-042 Part A addendum: fix `synthesizer.py` open P&L for NO positions
- For ISSUE-044: import `_today_pdt()` from `circuit_breaker.py` instead of defining duplicates

---

## Sign-off Status

**HOLD**

Part B cannot proceed as written — capital integrity is at risk (double-count or silent no-op). The three required changes are small and the DS can update the spec directly or flag back to CEO. Once those are incorporated, Part A and Part B are both ready for Dev.

ISSUE-076, ISSUE-047, ISSUE-043, ISSUE-044 are all **APPROVED** as written and can proceed immediately.

---

---

# Part B Re-Review
**Re-Reviewer:** Data Scientist  
**Date:** 2026-04-03  
**Trigger:** Updated spec incorporating all 3 Bug fixes from initial HOLD  
**Scope:** ISSUE-042 Part B only (all other issues previously approved)

## Verification of 3 Bug Fixes

### Fix 1 — `action: "exit_correction"` ✅ CONFIRMED

The updated spec correction record format now shows:
```json
"action": "exit_correction"
```
This matches the field name consumed by `compute_closed_pnl_from_logs()`. Records will be correctly read and summed into closed P&L. Bug 1 resolved.

### Fix 2 — No deposit to demo_deposits.jsonl ✅ CONFIRMED

Updated spec explicitly states:
> "Do NOT insert a deposit to `demo_deposits.jsonl`. The correction records alone are sufficient — adding a deposit would double-count the $7,863.61 (capital = deposits + closed P&L from logs, so both paths would add the same amount)."

Double-count risk eliminated. Correction records are the sole mechanism. Bug 2 resolved.

### Fix 3 — Step 11.5 added ✅ CONFIRMED

Sequencing table now includes:
> "11.5 | DS | Call `circuit_breaker.update_global_state(capital)` to refresh stale CB global state"

CB state file will be refreshed after log writes. Consistent with MEMORY.md standing rule. Bug 3 resolved.

### Math Check — ~$21,010 post-correction capital ✅ VERIFIED

- EOD capital (last recorded): ~$13,146
- Correction delta (115 trades, ep < 50, WS exits): +$7,863.61
- Expected corrected capital: $13,146.00 + $7,863.61 = **$21,009.61 ≈ ~$21,010**

Matches audit file conclusion: *"The correct capital should be approximately $21,009.61 once this P&L error is corrected."* ✅

---

## Part B Sign-off

**APPROVED**

All three bugs from the initial HOLD are resolved in the updated spec. The correction mechanism is now sound:
- Correct action type → records are read by `compute_closed_pnl_from_logs()`
- No deposit → no double-count
- Step 11.5 → CB state refreshed after log writes
- Math → $21,009.61 ≈ ~$21,010 ✓

ISSUE-042 Part B is **cleared to proceed** once Dev completes Part A and QA passes Step 9.
