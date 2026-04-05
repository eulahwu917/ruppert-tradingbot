# Batch 3 Trader Specs

**Author:** Trader  
**Date:** 2026-04-04  
**Reviewer target:** Adversarial reviewer → Dev

---

## B3-TRD-1: Daily Stop-Loss Missing `side == 'yes'` Gate

### Problem Statement

The daily stop-loss block in `position_tracker.py` (lines ~515–610) fires on both YES and NO positions for `crypto_threshold_daily_*` and `crypto_band_daily_*` modules. This is wrong.

The stop-loss logic compares `yes_bid` against `entry_price * threshold_pct`. This comparison is only meaningful for YES-side positions:

- **YES position**: You bought YES at e.g. 40c. If `yes_bid` drops to 6c (15% of 40c), you're losing money → stop fires correctly.
- **NO position**: You bought NO at e.g. 40c. The `yes_bid` moving *up* means your NO position is losing. If `yes_bid` rises to 80c, your NO position is underwater. But the stop-loss check compares `yes_bid < entry_price * 0.15`, which would only fire if `yes_bid` drops below 6c — i.e., the stop fires when the NO position is *winning*, not losing. This is backwards.

**Result:** For NO-side daily positions, the stop-loss fires in the wrong direction. It may incorrectly exit a winning NO position (if yes_bid is low) while silently ignoring a genuinely losing NO position (where yes_bid is high).

---

### How the Design D Block (crypto_dir_15m_) Already Handles This

The 15-minute Design D stop-loss block at ~line 441 already has the gate:

```python
if pos.get('module', '').startswith('crypto_dir_15m_') and pos.get('added_at') and side == 'yes':
```

The comment explicitly documents why:
> "YES-side only: Design D stops compare yes_bid < entry_price * pct. For NO positions (entry_price=3c), this would effectively never fire — NO-side exits are handled via the 'lte' threshold checks below."

The daily stop block never received the same treatment when it was added.

---

### Root Cause

The daily stop-loss outer `if` condition (~line 518) reads:

```python
if (_mod.startswith('crypto_threshold_daily_') or _mod.startswith('crypto_band_daily_')) and pos.get('added_at'):
```

It does not include a `side == 'yes'` gate. All four internal levels (Write-off, Catastrophic, Severe, Terminal) inherit this gap and apply to NO-side positions incorrectly.

---

### The Fix

#### What to change

Add `and side == 'yes'` to the outer `if` guard of the daily stop-loss block:

**Before (~line 518):**
```python
if (_mod.startswith('crypto_threshold_daily_') or _mod.startswith('crypto_band_daily_')) and pos.get('added_at'):
```

**After:**
```python
if (_mod.startswith('crypto_threshold_daily_') or _mod.startswith('crypto_band_daily_')) and pos.get('added_at') and side == 'yes':
```

No other changes inside the block are needed. The four internal tier checks (Write-off, Catastrophic, Severe, Terminal) all use `yes_bid` vs `entry_price * pct` — this is only valid for YES positions, so gating the whole block on `side == 'yes'` is correct.

#### Does NO-side need its own daily stop-loss logic?

**Not at this time.** Here's the reasoning:

1. **NO-side exits are handled by threshold checks.** The `lte` threshold type (which fires when `yes_bid <= threshold`) is the correct mechanism for NO-side exits. This already exists and is already in use.

2. **Daily NO positions have a different loss profile.** For a NO position, the adverse move is `yes_bid` rising. A proper NO-side daily stop would need to check `yes_bid > entry_price * (1 - loss_pct)` or similar. This is non-trivial to spec safely and introduces new risk.

3. **Write-off logic is also YES-side specific.** The Level 1 write-off (bid ≤ 1c near settlement) makes sense for YES — a 1c YES is essentially zero. For NO, `yes_bid = 1c` means your NO position is worth ~99c and winning. The write-off would incorrectly skip an exit on a winning NO position.

4. **Scope is Batch 3 bugfix, not new feature.** Adding NO-side stop-loss is new logic and belongs in a separate spec with its own QA cycle. The Batch 3 objective is to remove incorrect behavior.

**Conclusion:** Gate the block to YES-only now. Document the NO-side gap in a future backlog item.

---

### Exact File Location

**File:** `agents/ruppert/trader/position_tracker.py`  
**Line:** ~518 (the outer `if` that opens the daily stop block)  
**Context marker:** Look for the comment `# ── Stop-loss for crypto_band_daily_* and crypto_threshold_daily_* ──`

The line to modify is the `if` statement immediately following `_mod = pos.get('module', '')`.

---

### Add a Comment Explaining Why

After adding the gate, add a brief inline comment so the next reader doesn't repeat this bug:

```python
if (_mod.startswith('crypto_threshold_daily_') or _mod.startswith('crypto_band_daily_')) and pos.get('added_at') and side == 'yes':
    # YES-side only: all tier checks compare yes_bid < entry_price * pct.
    # For NO-side, yes_bid rising = loss (inverse). NO-side exits handled by 'lte' threshold checks.
```

---

### Risk Assessment

| Dimension | Assessment |
|---|---|
| Blast radius | Low — only affects `crypto_threshold_daily_*` and `crypto_band_daily_*` NO positions |
| Current NO daily positions | Verify none are open before deploying; if any exist, let them settle first |
| Regression risk | Minimal — the YES path is unchanged; only NO path behavior changes |
| Test vector needed | YES daily position should still stop correctly; NO daily position should NOT trigger any stop-loss |

---

### Out of Scope for This Fix

- NO-side daily stop-loss logic (new feature, future spec)
- Changes to the Design D (15-min) stop-loss block — it already has the gate
- Changes to threshold-based exits — they already work correctly for both sides

---

### Acceptance Criteria

1. The outer `if` guard at ~line 518 includes `and side == 'yes'`.
2. An inline comment explains why NO-side is excluded.
3. Code review confirms zero changes inside the block's four tier levels.
4. QA verifies: a simulated NO-side `crypto_threshold_daily_*` position with low `yes_bid` does **not** trigger any daily stop rule.
5. QA verifies: a simulated YES-side position with `yes_bid` below catastrophic threshold still triggers correctly.
