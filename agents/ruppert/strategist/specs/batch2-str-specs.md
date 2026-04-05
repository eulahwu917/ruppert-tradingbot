# Batch 2 Strategist Specs — Timezone Bug Fixes
_Author: Strategist | Date: 2026-04-04 | Status: Ready for adversarial review_

---

## Revision Log

| Date | Author | Section | Change |
|------|--------|---------|--------|
| 2026-04-04 | Strategist | B2-STR-2 | Added cross-spec dependency note: line 1320 deferral creates a known partial fix for settle record dates. B2-DS-1 reads `original_date` from the buy record via `pos.get('date', ...)`, so settle records written during the UTC midnight–PDT midnight window will still carry the wrong UTC date if line 1320 is unfixed. Tracked as a known gap; line 1320 added to Batch 5 date.today() sweep. |

---

## B2-STR-1: `circuit_breaker.py` — `check_global_net_loss()` reads wrong trade file for 7 hours/day

### What is broken

`check_global_net_loss()` builds the path to today's trade log using `date.today()`. On this machine, the system timezone is UTC. Between midnight UTC and midnight PDT — a 7-hour window each night — `date.today()` returns tomorrow's date in PDT terms. That means the function looks for a trade file that does not yet exist, finds nothing, reads $0 in losses, and the circuit breaker can never trip during this window no matter how much money the system loses.

This is a silent, invisible failure: no error is logged, the function returns `tripped: False`, and trading continues unguarded.

### What needs to change

In `circuit_breaker.py`, at **line 263**, there is this call:

```
f'trades_{date.today().isoformat()}.jsonl'
```

Replace `date.today().isoformat()` with a call to `_today_pdt()`.

`_today_pdt()` is **already defined in this same file at line 80**. It returns the current date string formatted as `YYYY-MM-DD` in Pacific Daylight Time. It is already used at lines 152, 181, 219, and 312 throughout the rest of `circuit_breaker.py` — this one site at line 263 was simply missed.

After the fix, the trade log path will consistently use PDT date strings, matching how trade files are named by the rest of the system.

### Verification

After the fix, `check_global_net_loss()` must produce the same trade file path that the rest of `circuit_breaker.py` produces. Confirm that `_today_pdt()` is called at line 263 (or wherever the `f'trades_{...}.jsonl'` path is constructed) and that `date.today()` no longer appears anywhere in `circuit_breaker.py`.

### Risk

Low. `_today_pdt()` is a proven helper already used throughout the same file. No behavior changes outside the 7-hour UTC/PDT overlap window. During that window, behavior changes from "CB always disabled" to "CB correctly enforced" — this is the desired outcome.

---

## B2-STR-2: `crypto_15m.py` — daily wager tracking uses system TZ at two sites

### Background

`crypto_15m.py` tracks how much has been wagered today in a module-level variable `_daily_wager`. This counter resets to zero when the current date string no longer matches `_daily_wager_date`. If the date comparison uses UTC instead of PDT, the counter resets at midnight UTC — 7 hours early — which means the daily wager cap check starts fresh in the middle of the PDT trading day, allowing more wagers than intended before the true PDT day boundary.

There is **no PDT helper defined inside `crypto_15m.py` itself**. The file imports `circuit_breaker` at line 112. The correct PDT helper to use is `circuit_breaker._today_pdt()`, which returns a `YYYY-MM-DD` string in Pacific time.

### Site 1 — Line 155: Startup state rehydration

**What this code does:** `_rehydrate_state()` runs once at startup to restore in-memory counters from the trade log. At line 155, it sets `_daily_wager_date` to `date.today().isoformat()` to establish the "current date" baseline for wager tracking.

**What is wrong:** If the system restarts between midnight UTC and midnight PDT, `_daily_wager_date` is set to tomorrow's PDT date. The wager counter will then never match `_daily_wager_date` during the actual PDT trading day, causing the counter to reset on every evaluation cycle — treating every trade as the start of a fresh day.

**Fix:** Replace `date.today().isoformat()` at line 155 with `circuit_breaker._today_pdt()`. This sets the startup date baseline in PDT, consistent with how the rest of the trading day is measured.

### Site 2 — Line 1232: Per-evaluation daily wager reset check

**What this code does:** Inside the trade evaluation loop, the code checks whether the calendar date has rolled over since the last trade. If it has, `_daily_wager` resets to zero and `_daily_wager_date` is updated. This is the live, real-time date check that controls the daily wager accumulation boundary.

**What is wrong:** `date.today().isoformat()` at line 1232 returns a UTC date. When UTC midnight crosses before PDT midnight, this check resets the wager counter 7 hours early — opening a second "daily budget" within the same PDT trading day. The system believes a new day has started and allows up to another full day's worth of wagers before PDT midnight actually arrives.

**Fix:** Replace `date.today().isoformat()` at line 1232 with `circuit_breaker._today_pdt()`. The reset check will then fire at PDT midnight, which is the correct day boundary for this system.

### Notes for Dev

- Do NOT create a new `_pdt_today()` or `_today_pdt()` helper inside `crypto_15m.py`. The correct approach is to call `circuit_breaker._today_pdt()`, which is already imported and available via the `from agents.ruppert.trader import circuit_breaker` import at line 112.
- There are two other `date.today()` calls in `crypto_15m.py` at lines 553 and 1320. These are **out of scope for this batch** — they are not part of the daily wager tracking path and are lower priority. Do not touch them in this batch.
- After the fix, both `_daily_wager_date` assignments (line 155 and line 1232) must use the same PDT-based date string format as `circuit_breaker._today_pdt()` returns (`YYYY-MM-DD`). Confirm the format is consistent.

### Cross-Spec Dependency Note (B2-STR-2 × B2-DS-1) — Added 2026-04-04

**Line 1320 is correctly deferred in this spec.** However, adversarial review identified a cross-spec interaction that creates a known partial fix:

- B2-DS-1 fixes the settle record's `entry_date` by using a PDT-aware date at write time.
- B2-DS-1 also reads `original_date` back from the *buy* record via `pos.get('date', ...)` when constructing the settle record.
- If a buy was written during the UTC midnight–PDT midnight window *before* line 1320 is patched, that buy record will carry a UTC-based (wrong) date in its `'date'` field.
- When B2-DS-1 later reads `pos.get('date', ...)` from that buy record, the settle record's `entry_date` will inherit the wrong UTC date — even after B2-DS-1 is deployed.

**Status:** Known gap, not blocking Batch 2. The partial fix from B2-DS-1 is still correct and valuable — it eliminates the timezone bug for all buys written after B2-STR-2 goes live (i.e., buys written outside the UTC/PDT overlap window, or after line 1320 is eventually patched).

**Resolution path:** Line 1320 (`'date': str(date.today())` on the buy record) must be added to the **Batch 5 `date.today()` sweep**. Once line 1320 is patched, buy records will carry correct PDT dates, and B2-DS-1's settle record fix will be fully effective end-to-end.

### Verification

Confirm:
1. Line 155: `_daily_wager_date` is set using `circuit_breaker._today_pdt()`, not `date.today()`.
2. Line 1232: The `today_str` comparison uses `circuit_breaker._today_pdt()`, not `date.today()`.
3. No new PDT helper function is introduced in `crypto_15m.py`.
4. Lines 553 and 1320 are untouched.

### Risk

Low-moderate. The wager counter reset logic is straightforward. The change aligns the reset boundary with PDT midnight, which is the intended behavior. The edge case to watch: if this fix is deployed mid-session between UTC midnight and PDT midnight (i.e., during the exact window the bug affects), the wager counter will no longer reset early — any wagers already placed in that session will be correctly counted against the current PDT day. This is correct behavior but Dev should note it in the PR.

---

_Specs authored by Strategist. These go to adversarial review before Dev implementation._
