# P1-SPRINT3 QA Report — Analytics + Calibration Pipeline
_QA Agent | Sprint: P1-3 | Date: 2026-04-03_
_Spec: P1-SPRINT3-SPEC.md (Revised) | Dev Notes: P1-SPRINT3-DEV-NOTES.md_

---

## Verdict: ✅ APPROVED — All 3 Batches + Patch

All 6 issues verified against spec. One observation noted (non-blocking).

---

## Files Reviewed

| File | Issues Covered |
|------|---------------|
| `agents/ruppert/strategist/optimizer.py` | ISSUE-005, ISSUE-041, ISSUE-046 |
| `environments/demo/brier_tracker.py` | ISSUE-004, ISSUE-101 (+ patch) |
| `environments/demo/prediction_scorer.py` | ISSUE-103 |

---

## Issue-by-Issue Verification

---

### ISSUE-005 — optimizer.py: load_trades() glob path fix

**Status: ✅ PASS**

**Spec requirement:** Change `LOGS_DIR.glob("trades_*.jsonl")` → `(LOGS_DIR / "trades").glob("trades_*.jsonl")`

**Verified in `load_trades()`:**
```python
patterns = [
    (LOGS_DIR / "trades").glob("trades_*.jsonl"),
    ARCHIVE_DIR.glob("trades_*.jsonl") if ARCHIVE_DIR.exists() else iter([]),
]
```

Fix correctly applied. Archive glob unchanged (still targets `ARCHIVE_DIR`, correct). Empty iterator fallback for missing archive directory preserved.

---

### ISSUE-041 — optimizer.py: analyze_daily_cap_utilization() buy-only filter

**Status: ✅ PASS**

**Spec requirement:** Add `if t.get("action") not in ("buy", "open"): continue` before summing `size_dollars`.

**Verified in `analyze_daily_cap_utilization()`:**
```python
for t in trades:
    if t.get("action") not in ("buy", "open"):
        continue
    ts = t.get("timestamp", "")
    size = t.get("size_dollars", 0.0)
```

Filter is correctly placed before summing. Only `buy`/`open` action records contribute to daily capital totals. Exit/settle records no longer double-count.

---

### ISSUE-004 — brier_tracker.py: Lazy path resolution via _get_brier_paths()

**Status: ✅ PASS**

**Spec requirement:**
- Remove module-level `_LOGS_DIR`, `_PRED_FILE`, `_SCORED_FILE` constants
- Add `_get_brier_paths()` lazy helper resolving via `env_config.get_paths()` at call time
- All 3 functions (`log_prediction`, `score_prediction`, `get_domain_brier_summary`) call `_get_brier_paths()` at function scope

**Verified:**

Module-level path constants are absent. ✅

`_get_brier_paths()` is correctly implemented:
```python
def _get_brier_paths():
    workspace_root = Path(__file__).resolve().parent.parent.parent
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))
    from agents.ruppert.env_config import get_paths
    paths = get_paths()
    logs_dir = paths['logs']
    return logs_dir, logs_dir / "predictions.jsonl", logs_dir / "scored_predictions.jsonl"
```
✅ `sys.path` guard present. ✅ Import deferred to call time. ✅ Returns `(logs_dir, pred_file, scored_file)` tuple.

**`log_prediction`:** Calls `_get_brier_paths()` inside `try:` block. ✅ env_config errors caught by existing try/except.

**`score_prediction`:** Calls `_get_brier_paths()` inside `try:` block. ✅ env_config errors caught by existing try/except.

**`get_domain_brier_summary`:** Calls `_get_brier_paths()` at function scope, before `try:` block. ✅ Matches spec example code exactly. Import-time crash prevention (the primary goal) is achieved. See Observation below.

`import sys` is present at module level. ✅

---

### ISSUE-101 — brier_tracker.py: (ticker, date) dedup + patch

**Status: ✅ PASS**

**Spec requirement (post-patch):** Dedup key is `(ticker, date)` where `date = ts[:10]` from BOTH the prediction being scored AND the existing scored record — NOT `resolved_at[:10]` on the existing record side. Null-outcome records block re-scoring (dedup checks key existence only, not outcome value).

**Verified in `score_prediction()`:**

```python
prediction_date = str(prediction.get("ts", ""))[:10]  # "YYYY-MM-DD" from ISO timestamp (entry date)
if _scored_file.exists():
    for existing_line in _scored_file.read_text(encoding="utf-8").strip().splitlines():
        try:
            existing_rec = json.loads(existing_line)
            # ISSUE-101 fix: use prediction entry date (ts[:10]) on both sides.
            # resolved_at is set at score-time and can differ from entry date for
            # afternoon PDT positions that settle past midnight UTC.
            existing_entry_date = str(existing_rec.get("ts", ""))[:10]
            if (existing_rec.get("ticker") == ticker
                    and existing_entry_date == prediction_date):
                logger.debug(
                    f"[Brier] Duplicate score suppressed for {ticker} "
                    f"on {prediction_date} -- already in scored file"
                )
                return
        except Exception:
            continue
```

✅ **Patch correctly applied**: both sides use `ts[:10]` (prediction entry date). `resolved_at` is NOT used on the existing record side. The original `resolved_at[:10]` comparison noted in the batch 2 dev notes has been replaced with `existing_entry_date = str(existing_rec.get("ts", ""))[:10]`.

✅ **Null-outcome blocking**: dedup does NOT check `outcome is not None`. Any record with a matching `(ticker, date)` key in the scored file blocks re-scoring, regardless of whether its `outcome` field is null.

✅ **Dedup placement**: block is placed after `if prediction is None: return` guard and before `scored_entry` is built.

✅ **Debug log**: emitted on duplicate suppression.

---

### ISSUE-103 — prediction_scorer.py: (ticker, side) fallback index

**Status: ✅ PASS**

**Spec requirement:**
- Secondary fallback `buy_index_by_ticker_side` keyed on `(ticker, side)`
- No-match returns `predicted_prob = None` (not a default float)
- Warning logs on both fallback paths
- `side` comes from settle record

**Verified — index construction:**
```python
buy_index_by_ticker_side: dict[tuple, dict] = {}
for rec in all_trades:
    action = rec.get('action', '')
    if action in ('buy', 'open'):
        primary_key = (rec.get('ticker', ''), rec.get('date', ''))
        if primary_key not in buy_index:
            buy_index[primary_key] = rec
        ts_key = (rec.get('ticker', ''), rec.get('side', 'yes'))
        if ts_key not in buy_index_by_ticker_side:
            buy_index_by_ticker_side[ts_key] = rec
```
✅ Both indexes populated in same scan. ✅ First-seen buy record stored (correct for now per ISSUE-050 note).

**Verified — lookup:**
```python
settle_side = rec.get('side', 'yes')
buy_rec = buy_index.get(key) or buy_index_by_ticker_side.get((ticker, settle_side))
```
✅ `side` comes from settle record (`rec.get('side', 'yes')`). ✅ `(ticker, side)` key on fallback.

**Verified — warning logs on both fallback paths:**
```python
if not buy_index.get(key):
    if buy_rec:
        logger.warning(
            f"[Scorer] {ticker}: date mismatch -- using (ticker, side) fallback ..."
        )
    else:
        logger.warning(
            f"[Scorer] {ticker}: no matching buy record found for ... -- predicted_prob will be null"
        )
```
✅ Warning on successful fallback (date mismatch, ticker+side matched). ✅ Warning on no-match.

**Verified — `predicted_prob = None` when no match:**
```python
predicted_prob = buy_rec.get('noaa_prob') if buy_rec else None
if predicted_prob is None:
    predicted_prob = buy_rec.get('model_prob') if buy_rec else None
if predicted_prob is None:
    predicted_prob = buy_rec.get('market_prob') if buy_rec else None
```
✅ All three prob field lookups guard `if buy_rec else None`. No default float written. If `buy_rec is None`, `predicted_prob` stays `None`.

**Verified — logging module added:**
```python
import logging
logger = logging.getLogger(__name__)
```
✅ `import logging` and logger instantiation present. Dev notes confirm this was missing before.

**Verified — downstream `buy_rec` accesses guarded:**
- `module`, `city`, `edge`, `confidence`: all use `if buy_rec else None/default` pattern ✅
- Side flip: `side = rec.get('side') or (buy_rec.get('side', 'yes') if buy_rec else 'yes')` ✅
- `scored_entry` edge/confidence: guarded with `if buy_rec and buy_rec.get(...) is not None else None` ✅

---

### ISSUE-046 — optimizer.py: analyze_exit_timing() full fix

**Status: ✅ PASS**

**Spec requirement:**
- `analyze_exit_timing()` takes `buy_index=None` param
- `count = len(pnls)` (not `len(hold_times)`)
- `build_report()` called with updated return dict
- Existing callers not broken

**Verified — signature:**
```python
def analyze_exit_timing(trades: list, buy_index: dict = None):
```
✅ `buy_index=None` default parameter.

**Verified — hold time computation:**
- `exit_ts` from `t.get("timestamp")` (the exit/settle record's own timestamp) ✅
- `entry_ts` from `buy_index.get(ticker).get("timestamp")` via buy_index param ✅
- Non-existent `exit_timestamp` field is gone ✅

**Verified — P&L collection:**
```python
pnl = t.get("pnl") if t.get("pnl") is not None else t.get("realized_pnl")
if pnl is not None:
    try:
        pnls.append(float(pnl))
    except (ValueError, TypeError):
        pass
```
✅ Both `pnl` and `realized_pnl` fallback.

**Verified — KEY FIX — `count = len(pnls)`:**
```python
return {
    "count": len(pnls),          # KEY FIX: was len(hold_times) — now len(pnls)
    "avg_hold_hours": statistics.mean(hold_times) if hold_times else None,
    "avg_pnl": statistics.mean(pnls) if pnls else None,
}
```
✅ `count` is `len(pnls)`. Exit timing section in `build_report()` will display whenever settled trades with P&L exist, even if hold time correlation fails.

**Verified — buy_index_for_exits built in main() before call:**
```python
buy_index_for_exits = {}
for t in trades:
    if t.get("action") in ("buy", "open"):
        ticker = t.get("ticker", "")
        if ticker and ticker not in buy_index_for_exits:
            buy_index_for_exits[ticker] = t

exit_timing = analyze_exit_timing(trades, buy_index_for_exits)
```
✅ Index built from enriched trades (buy/open records only). ✅ First-seen buy per ticker. ✅ Passed into `analyze_exit_timing`.

**Verified — build_report() call unchanged in structure:**
```python
report_text, proposals = build_report(
    trades, module_wr, tier_wr, exit_timing, brier, cap_util, sizing, today_str,
    has_outcome_data=has_outcome_data,
)
```
✅ `exit_timing` dict with `count`/`avg_hold_hours`/`avg_pnl` keys matches what `build_report()` reads via `exit_timing["count"]`, `exit_timing["avg_hold_hours"]`, `exit_timing["avg_pnl"]`. No changes to `build_report()` itself needed or made.

---

## Observation (Non-Blocking)

**OBSERVATION — `get_domain_brier_summary`: `_get_brier_paths()` outside try/except**

In `get_domain_brier_summary`, the `_get_brier_paths()` call is placed before the `try:` block:

```python
def get_domain_brier_summary() -> dict:
    THRESHOLD = 30
    summary = {}
    _logs_dir, _pred_file, _scored_file = _get_brier_paths()  # outside try:
    if not _scored_file.exists():
        return summary
    try:
        ...
    except Exception as e:
        logger.warning(...)
```

This means an env_config failure in `_get_brier_paths()` would propagate to callers of `get_domain_brier_summary` rather than being caught internally. In contrast, `log_prediction` and `score_prediction` correctly call `_get_brier_paths()` inside their `try:` blocks.

**This is conformant to the spec** — the spec's example code for `get_domain_brier_summary` shows this exact pattern. The primary goal (no import-time crash) is fully achieved. The observation is logged for completeness.

**Action: none required.** If `get_domain_brier_summary` callers have their own try/except (which they should), this propagates safely. A follow-up can wrap the call if needed.

---

## QA Self-Test Cross-Check

Dev reports `33/33 PASS` on `audit/qa_self_test.py` and `PASS WITH WARNINGS` on `audit/config_audit.py` (6 Task Scheduler warnings pre-existing, unrelated to sprint). Import checks for all 3 files: OK.

No contradictions found between dev self-test results and manual code review.

---

## Commit Messages

### Batch 1 — `agents/ruppert/strategist/optimizer.py`
```
fix(optimizer): ISSUE-005 correct load_trades() glob to logs/trades/ subdir; ISSUE-041 filter buy/open only in analyze_daily_cap_utilization()
```

### Batch 2 — `environments/demo/brier_tracker.py`
```
fix(brier_tracker): ISSUE-004 lazy path resolution via _get_brier_paths(); ISSUE-101 (ticker,date) dedup using ts[:10] on both sides, null-outcome records block re-scoring
```

### Batch 3 — `environments/demo/prediction_scorer.py` + `agents/ruppert/strategist/optimizer.py`
```
fix(scorer,optimizer): ISSUE-103 (ticker,side) fallback index with null return on no-match and warning logs; ISSUE-046 analyze_exit_timing full fix — buy_index param, count=len(pnls), buy_index_for_exits in main()
```

---

## Summary

| Issue | File | Status |
|-------|------|--------|
| ISSUE-005 | optimizer.py | ✅ PASS |
| ISSUE-041 | optimizer.py | ✅ PASS |
| ISSUE-004 | brier_tracker.py | ✅ PASS |
| ISSUE-101 | brier_tracker.py | ✅ PASS (patch applied correctly) |
| ISSUE-103 | prediction_scorer.py | ✅ PASS |
| ISSUE-046 | optimizer.py | ✅ PASS |

**Overall: APPROVED. Ready to commit.**

_QA Agent — P1-Sprint3 — 2026-04-03_
