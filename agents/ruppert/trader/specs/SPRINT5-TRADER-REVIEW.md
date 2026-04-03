# Sprint 5 Trader Review
**Date:** 2026-04-03  
**Reviewer:** Trader agent  
**Spec:** `agents/ruppert/data_scientist/specs/SPRINT5-SPEC.md`  
**Status:** ✅ APPROVED WITH NOTES

---

## Sign-Off

The spec is sound. Core logic is correct across all three focus areas. Notes below are implementation guardrails — none are blockers, but two (#1 and #2) must be addressed within the same commit as the flip removal to prevent a silent production bug.

---

## Focus Area 1: ISSUE-042 Part A — NO-side flip removal + Design D gating

### Stop math verification

**NO at 3c after the fix:**
- `entry_price = 3` (stored correctly, no flip)
- `size_dollars = 3 * qty / 100` = correct cost basis

**Design D tiers (currently applied to ALL crypto_dir_15m_ positions):**
- Catastrophic: `yes_bid < 3 * 0.20 = 0.6c` → fires when yes_bid = 0
- Severe: `yes_bid < 3 * 0.30 = 0.9c` → fires when yes_bid = 0 (integer arithmetic)
- Terminal: `yes_bid < 3 * 0.40 = 1.2c` → fires when yes_bid = 0 or 1c

**Critical**: These are YES-side stops. For a NO position at 3c, `yes_bid` going UP is what hurts us — YES at 90c means our NO is worth 10c, which is a 70% loss. Design D stops compare `yes_bid < low_threshold` which fires when YES drops near zero — that's when NO is *winning*. The spec is 100% correct: these stops are wrong for NO positions and the `and side == 'yes'` gate is required.

**70% gain exit threshold (compare='lte') after fix:**
```
no_gain_target = 100 - (3 + 0.90 * (100 - 3))
               = 100 - (3 + 87.3)
               = 9.7c
```
Trigger: `yes_bid ≤ 9.7c` — YES drops to 9.7c or below, NO position gained 70%+. ✓

**Before the fix** (entry_price stored as 97 due to flip):
```
no_gain_target = 100 - (97 + 0.90 * (100 - 97))
               = 100 - 99.7 = 0.3c
```
The 70% gain exit effectively never fired (threshold was 0.3c). This confirms the bug was real.

**The compare='lte' direction is correct.** NO exits when YES bid drops, not rises. ✓

### Note 1 — Migration block removal must be atomic with flip removal (REQUIRED)

The spec correctly says to remove `_load()`'s migration block. This is **not optional timing** — it must happen in the same commit as removing the flip from `add_position()`.

**Why**: After the fix, a correctly-stored NO position at 3c has `entry_price = 3`. The migration block runs on startup and checks: `if side='no' and entry_price < 50`. `3 < 50` is True → migration flips it to `100 - 3 = 97`. If Dev removes the flip from `add_position()` but leaves the migration in `_load()`, any open NO position would be re-broken at the next ws_feed restart.

**QA must verify**: commit diff shows both changes present together. Cannot be split across PRs.

### Note 2 — Stale comments in execute_exit() and check_expired_positions() (SHOULD FIX)

After the flip is removed, `entry_price` for NO positions is reliable. These two comments are stale and will mislead future readers:

**In `execute_exit()` settle_loss path (~line 530):**
```python
# NO-side loss: use size_dollars as the true cost (entry_price is unreliable
# due to the NO-side flip in add_position — 15m passes correct NO price but
# flip converts e.g. 3c → 97c, inflating the calculated loss).
```
After the fix, entry_price IS reliable. Update comment to: `# NO-side loss: cost = size_dollars (entry_price * qty / 100)`

**In `check_expired_positions()` NO settlement block (~line 620):**
```python
# NO side: entry_price is unreliable due to the NO-side flip in
# add_position() (15m passes correct NO price but flip converts
# e.g. 3c → 97c). Use size_dollars for losses, formula for wins.
```
Same issue. Update to reflect that entry_price is now the correct NO price.

The P&L formulas in these blocks are correct after the fix — only the justifying comments are wrong. But leaving wrong comments here is a trap for anyone auditing future NO-side P&L discrepancies.

---

## Focus Area 2: ISSUE-076 — portalocker in async ws_feed

### Does it work with async?

**Short answer: Yes, with a caveat.**

`portalocker.LOCK_EX` is a blocking syscall. When called from an async function in ws_feed.py's event loop, it blocks the entire event loop thread while waiting to acquire the lock.

**Why this is acceptable in practice:**
1. The lock hold time is sub-millisecond — tiny JSON read/modify/write
2. Lock contention in this path is rare (only when two assets exit simultaneously)
3. Even if blocked, the event loop resumes after microseconds
4. Python's asyncio cooperative scheduling means two tasks in the same event loop can't actually race without an `await` between them anyway — the TOCTOU risk is primarily a **cross-process** concern (ws_feed + post_trade_monitor running as separate OS processes)

**The real race being solved**: ws_feed and post_trade_monitor run as separate processes. portalocker works correctly for that. ✓

### Note 3 — File-not-found on first run (implementation detail)

The spec describes opening in `r+` mode "(or `w+` if it doesn't exist yet)." Dev must handle the `FileNotFoundError` correctly:

```python
try:
    fh = open(path, 'r+')
except FileNotFoundError:
    fh = open(path, 'w+')
```

If Dev does `open(path, 'r+')` unconditionally, first-run startup will crash. The spec mentions this but it's easy to miss in implementation. QA should test cold start (no CB state file).

---

## Focus Area 3: ISSUE-043 — EXIT_GAIN_PCT hardening

**No concerns.** This is clean.

The `raise ImportError` fires at module import time. If config is intact (it is — `EXIT_GAIN_PCT = 0.90` is on line 374), startup is unaffected. If config is broken, the loud failure is exactly what we want instead of silently using 0.70.

Only way this breaks startup is if config.py itself fails to import — but that would already crash position_tracker.py before reaching this check. The hardening adds zero new startup risk in normal deployment. ✓

---

## Summary Table

| Issue | Math/Logic | Implementation Risk | Status |
|-------|-----------|---------------------|--------|
| ISSUE-042 Part A | ✅ Correct | ⚠️ Migration + flip must be removed atomically | APPROVED WITH NOTE 1+2 |
| ISSUE-076 | ✅ Correct | ⚠️ Cold-start r+ file open | APPROVED WITH NOTE 3 |
| ISSUE-043 | ✅ Correct | None | APPROVED |

---

## QA Checklist (from Trader)

On top of the spec's sequencing table, QA should verify:

1. **Atomicity**: migration block removal and flip removal are in the same commit
2. **Cold start**: delete CB state file, start ws_feed → no crash (tests Note 3)
3. **NO at 3c entry**: tracked position shows `entry_price=3`, `size_dollars=0.03 * qty`
4. **NO exit threshold**: position built with `entry_price=3` → `no_gain_target ≈ 9.7c`, `compare='lte'` fires at yes_bid ≤ 9c (integer)
5. **Design D skip**: crypto_dir_15m_ NO position at 3c does NOT trigger Tier 1/2/3 stops when yes_bid is low (e.g. 0c). Stops should be skipped entirely for side='no'.
6. **Settlement loss path**: open NO at 3c, simulate YES wins → P&L = -(3 * qty / 100), not -(97 * qty / 100)

---

_Trader sign-off: Sprint 5 is approved to proceed to Dev with notes above addressed._

---

## Sprint 5 Pre-QA: Design D `side` Variable Review

**Date:** 2026-04-03  
**Question:** `key[1]` vs `pos.get('side')` for the Design D YES-only guard

### Answer: `side = key[1]` is correct and preferred

**Reasoning:**

1. **`key[1]` is canonical.** The loop iterates `for key in matching_keys` where `key = (ticker, side)`. The key is the source of truth for which position we're on — `_tracked` is keyed by `(ticker, side)`. Reading from the key is more authoritative than reading from the dict value.

2. **`pos.get('side')` works but is redundant.** The dict has a `'side'` field, but it's derived from the key at `add_position()` time. No new variable needed, but it's a secondary source with a `.get()` default-None risk (shouldn't happen, but key is tighter).

3. **`side = key[1]` fixes more than the Design D guard.** Looking at the daily stop block (the `crypto_band_daily_` / `crypto_threshold_daily_` block further down in the same loop body), there's already a reference to `side` here:
   ```python
   _wo_key = (ticker, side, int(_mins_left))
   ```
   Without `side = key[1]`, this line would throw a `NameError` at runtime whenever a daily stop write-off fires. Adding `side = key[1]` at the top of the loop body fixes both references in one go.

### Scope check: No conflicts

`side` is not defined anywhere else in the `check_exits()` function body or its signature. The function takes `(ticker, yes_bid, yes_ask, close_time)` — no `side` parameter. Assigning `side = key[1]` at the top of the `for key in matching_keys` loop creates a clean local that's valid for the entire loop iteration. Zero conflicts.

### Verdict

**`side = key[1]` — correct and required.** Not just preferred — it's the fix that also resolves the pre-existing undefined `side` reference in the daily stop write-off dedup line. `pos.get('side')` would work for the Design D condition only, but would leave the daily block broken.

QA should verify: on a `crypto_band_daily_` position with `yes_bid <= 1` near write-off time, the `_wo_key` tuple builds correctly without `NameError`.
