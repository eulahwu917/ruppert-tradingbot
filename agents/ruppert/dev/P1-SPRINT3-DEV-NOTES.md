# P1-SPRINT3 Dev Notes
_Developer: Dev subagent | Sprint: P1-3 | Date: 2026-04-03_

---

## Batch 1 — ISSUE-005 + ISSUE-041
**Files changed:** `agents/ruppert/strategist/optimizer.py`
**Status:** Implemented — awaiting QA

### ISSUE-005: load_trades() glob path fix
- Changed `LOGS_DIR.glob("trades_*.jsonl")` → `(LOGS_DIR / "trades").glob("trades_*.jsonl")`
- LOGS_DIR = `environments/demo/logs/`; trades are in `environments/demo/logs/trades/`
- Archive glob unchanged (already targets ARCHIVE_DIR correctly)
- Risk: minimal — glob returns empty iterator if path doesn't exist, handled gracefully

### ISSUE-041: analyze_daily_cap_utilization() buy-only filter
- Added `if t.get("action") not in ("buy", "open"): continue` before summing size_dollars
- Prevents exit/settle records from double-counting capital deployed
- Relies on action normalization in logger.py (already lowercased to 'buy')
- Depends on ISSUE-005 for real data to flow through

---

## Batch 2 — ISSUE-004 + ISSUE-101
**Files changed:** `environments/demo/brier_tracker.py`
**Status:** Implemented — awaiting QA

### ISSUE-004: Lazy path resolution via _get_brier_paths()
- Removed module-level `_LOGS_DIR`, `_PRED_FILE`, `_SCORED_FILE` constants
- Added `_get_brier_paths()` helper that resolves paths at call time via env_config
- Added `import sys` at module level (was missing, needed for sys.path guard in helper)
- Helper adds workspace root to sys.path if not already present, then imports env_config
- All three functions (`log_prediction`, `score_prediction`, `get_domain_brier_summary`) now
  call `_get_brier_paths()` at the top of each function body
- Import-time crashes from env_config unavailability now caught by each function's
  existing `try/except` instead of crashing the module import
- RUPPERT_ENV changes after import are now respected per-call
- Import test: `import brier_tracker` → OK (no crash even without env_config context)

### ISSUE-101: (ticker, date) dedup in score_prediction()
- Dedup block placed after `if prediction is None: return` guard, before `scored_entry` build
- Key: `(ticker, prediction_date)` where `prediction_date = str(prediction.get("ts", ""))[:10]`
- Compared against `str(existing_rec.get("resolved_at", ""))[:10]` in scored file (original impl)
- Dedup does NOT condition on `outcome is not None` — null-outcome records block re-scoring
- Debug log emitted when duplicate suppressed

### ⚠️ PATCH APPLIED 2026-04-03 — ISSUE-101: resolved_at → ts[:10] on existing_rec side
- **Root cause confirmed:** `resolved_at` is set at score-time, not prediction entry time.
  Afternoon PDT positions settle past midnight UTC: `prediction.ts[:10]` = Day 1,
  `existing_rec.resolved_at[:10]` = Day 2 → dedup key mismatch → same prediction double-scored.
- **Fix:** Both sides of the dedup comparison now use `prediction entry date` (`ts[:10]`).
  - `prediction_date = str(prediction.get("ts", ""))[:10]`  ← unchanged
  - `existing_entry_date = str(existing_rec.get("ts", ""))[:10]`  ← NEW (was resolved_at)
  - Comparison: `existing_entry_date == prediction_date`  ← NEW (both are entry dates)
- Scored entries include `{**prediction, ...}` so `ts` is always present in existing records.
- **Not yet committed — awaiting QA clearance.**

---

## Batch 3 — ISSUE-103 + ISSUE-046
**Files changed:** `environments/demo/prediction_scorer.py`, `agents/ruppert/strategist/optimizer.py`
**Status:** Implemented — awaiting QA

### ISSUE-103: (ticker, side) fallback index in prediction_scorer.py
- Added `import logging` and `logger = logging.getLogger(__name__)` (was print-only before)
- Added `buy_index_by_ticker_side` dict alongside existing `buy_index`
- Both populated during the same buy/open record scan
- `settle_side` read from settle record first (falls back to 'yes' if absent)
- Lookup: `buy_rec = buy_index.get(key) or buy_index_by_ticker_side.get((ticker, settle_side))`
- If neither succeeds, `buy_rec = None`
- Warning logged for both fallback paths:
  - Success fallback: date mismatch, (ticker, side) match found
  - No-match: no buy record exists for (ticker, side)
- All downstream `buy_rec` accesses guarded with `if buy_rec else None/default`:
  - `module`, `city`, `predicted_prob` (all three prob fields), `side`, `edge`, `confidence`
- If `buy_rec is None`: `predicted_prob = None`, `brier_score = None` — no corrupt float written
- Scored entry still written with null fields — occupies processed-key slot, prevents re-scoring

### ISSUE-046: analyze_exit_timing() full fix in optimizer.py
- Changed signature: `analyze_exit_timing(trades: list, buy_index: dict = None)`
- `exit_ts` now reads from `t.get("timestamp")` on exit/settle records (the nonexistent
  `exit_timestamp` field removed)
- `entry_ts` now comes from `buy_index.get(ticker).get("timestamp")` via new param
- **KEY FIX**: `count = len(pnls)` not `len(hold_times)` — ensures section displays when
  settled trades exist even if buy/exit hold time correlation fails
- `avg_hold_hours` can be `None` even when `count > 0` — build_report() handles gracefully
  with existing `if avg_hold is not None:` guard
- In `main()`: built `buy_index_for_exits` dict (ticker → first buy record) before analysis
- `analyze_exit_timing(trades, buy_index_for_exits)` call updated

---

## QA Self-Test Results (post all-batch implementation)
- `python audit/qa_self_test.py`: **33/33 PASS**
- `python audit/config_audit.py`: **PASS WITH WARNINGS** (6 Task Scheduler state warnings — pre-existing, unrelated to this sprint)
- Import checks:
  - `optimizer.py`: OK (from environments/demo workdir)
  - `brier_tracker.py`: OK
  - `prediction_scorer.py`: OK

---

## Files Modified
1. `agents/ruppert/strategist/optimizer.py` — ISSUE-005, ISSUE-041, ISSUE-046
2. `environments/demo/brier_tracker.py` — ISSUE-004, ISSUE-101
3. `environments/demo/prediction_scorer.py` — ISSUE-103

## NOT committed — awaiting QA clearance per pipeline rules
