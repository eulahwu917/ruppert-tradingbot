# P1 Sprint 3 Spec — Analytics + Calibration Pipeline
_Authored: 2026-04-03 | Data Scientist_
_Basis: P1-DS-REVIEW.md_
_Revised: 2026-04-03 | Post-adversarial review (4 issues revised)_

---

## Revision Summary (Post-Adversarial Review)

Four issues were flagged as needing revision before Dev build:

| Issue | Revision |
|-------|----------|
| ISSUE-004 | Changed from module-level env_config import+call to lazy-init inside each function. Eliminates import-time crash and RUPPERT_ENV freeze-at-first-import. |
| ISSUE-101 | Changed dedup key from `ticker` alone to `(ticker, date)` to prevent silent dedup of same-ticker trades on different dates. Added explicit handling for records with `outcome: null` — dedup now keys on existence only, not outcome value. |
| ISSUE-103 | Changed ticker-only fallback to `(ticker, side)` fallback. Ticker-only fallback is worse than null for re-traded tickers (corrupt Brier score passes through silently; null is filtered). If no `(ticker, side)` match, `predicted_prob` stays `None` — do NOT corrupt. |
| ISSUE-046 | Replaced broken minimal fix with full fix. Minimal fix left `count = len(hold_times) = 0`, triggering the `if et_count == 0` guard in `build_report()` and hiding all P&L data. Full fix: build buy/exit join by ticker, change `count = len(pnls)`, P&L and hold time now both visible. |

ISSUE-005 and ISSUE-041 were marked SOLID and are unchanged from the original spec.

---

## Issues Covered

| Issue | File | Summary |
|-------|------|---------|
| ISSUE-005 | optimizer.py | load_trades() globs wrong directory |
| ISSUE-004 | brier_tracker.py | Hardcoded log path — lazy-init fix |
| ISSUE-101 | brier_tracker.py | Duplicate scoring — (ticker, date) dedup + null-outcome handling |
| ISSUE-103 | prediction_scorer.py | Wrong fallback for multi-day positions — (ticker, side) keyed fallback |
| ISSUE-041 | optimizer.py | analyze_daily_cap_utilization() double-counts exits |
| ISSUE-046 | optimizer.py | analyze_exit_timing() — full buy/exit join fix |

---

## ISSUE-005 — optimizer.py: load_trades() globs wrong directory

### What to change

In `agents/ruppert/strategist/optimizer.py`, the `load_trades()` function contains this line:

```python
LOGS_DIR.glob("trades_*.jsonl"),
```

`LOGS_DIR` is set at the top of the file to `_env_paths['logs']`, which resolves to `environments/demo/logs/`. But trade files are written to `environments/demo/logs/trades/` (the `trades` key from `env_config.get_paths()`). The glob is one directory level too shallow and matches nothing.

Change that line to:

```python
(LOGS_DIR / "trades").glob("trades_*.jsonl"),
```

No other changes needed. The archive glob on the next line is already correct — it targets `ARCHIVE_DIR` which is `LOGS_DIR / "archive-pre-2026-03-26"` and trade files there follow the same filename pattern.

### What behavior changes

Before the fix: every optimizer run returns zero trades. All analyses (win rate, cap utilization, exit timing, Brier, sizing) produce empty or zero output. The optimizer proposals report is completely hollow.

After the fix: the optimizer reads the actual trade log files and produces real output. This is the prerequisite fix for ISSUE-041 and ISSUE-046 to matter at all.

### What could go wrong

Nothing risky. The path change is additive and narrowing — we're pointing deeper into the same directory tree. If `logs/trades/` doesn't exist (first run on a fresh environment), the glob returns an empty iterator and `load_trades()` returns an empty list, which is handled gracefully.

---

## ISSUE-004 — brier_tracker.py: Hardcoded path (revised)

### What to change

In `environments/demo/brier_tracker.py`, the log directory and file paths are hardcoded relative to the script file itself:

```python
_LOGS_DIR = Path(__file__).parent / "logs"
_PRED_FILE = _LOGS_DIR / "predictions.jsonl"
_SCORED_FILE = _LOGS_DIR / "scored_predictions.jsonl"
```

**Remove these three module-level constants entirely.** Do not replace them with a module-level `env_config` call.

Instead, add a private helper function that resolves paths at call time:

```python
import sys
from pathlib import Path

def _get_brier_paths():
    """
    Lazy path resolution — called at function scope, not import scope.
    Resolves env-config paths each time it's called so RUPPERT_ENV changes
    after import are respected (important for test isolation).
    Returns (logs_dir, pred_file, scored_file).
    """
    workspace_root = Path(__file__).resolve().parent.parent.parent
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))
    from agents.ruppert.env_config import get_paths
    paths = get_paths()
    logs_dir = paths['logs']
    return logs_dir, logs_dir / "predictions.jsonl", logs_dir / "scored_predictions.jsonl"
```

Then in `log_prediction()`, `score_prediction()`, and `get_domain_brier_summary()`, replace every reference to `_LOGS_DIR`, `_PRED_FILE`, and `_SCORED_FILE` with a call to `_get_brier_paths()` at the top of each function:

```python
def log_prediction(domain, ticker, predicted_prob, market_price, edge, side="", extra=None):
    try:
        _logs_dir, _pred_file, _scored_file = _get_brier_paths()
        _logs_dir.mkdir(exist_ok=True)
        # ... rest of function uses _pred_file instead of _PRED_FILE ...
```

```python
def score_prediction(ticker, outcome):
    try:
        _logs_dir, _pred_file, _scored_file = _get_brier_paths()
        if not _pred_file.exists():
            return
        # ... rest of function uses _pred_file, _scored_file, _logs_dir ...
```

```python
def get_domain_brier_summary():
    THRESHOLD = 30
    summary = {}
    _logs_dir, _pred_file, _scored_file = _get_brier_paths()
    if not _scored_file.exists():
        return summary
    # ... rest of function uses _scored_file ...
```

The `predictions.jsonl` and `scored_predictions.jsonl` filenames remain unchanged; only the directory is now env-config-driven and resolved lazily.

### Why lazy init instead of module-level

The original spec proposed placing `from agents.ruppert.env_config import get_paths` at module scope. That approach has two problems:

1. **Import-time crash**: If `env_config` is unavailable in a given execution context, the entire `brier_tracker` module fails to import. Any caller doing `from environments.demo.brier_tracker import log_prediction` crashes immediately, with no fallback. The functions that are wrapped in `try/except` (e.g., `log_prediction`) offer zero protection because the exception occurs before any function is entered.

2. **RUPPERT_ENV freeze**: Module-level constants are computed once when the module is first imported. If `RUPPERT_ENV` is changed after import (e.g., in test code running demo and live environments sequentially), the paths won't update. This is the same class of bug as the original hardcoded path, just deferred.

The `_get_brier_paths()` helper resolves paths fresh on every call, making it immune to both problems.

### What behavior changes

Before: paths always point to `environments/demo/logs/` regardless of the active environment. An import-time env_config failure kills the module. In live mode the brier tracker silently writes to the demo environment.

After: paths resolve through `env_config.get_paths()` inside each function. Import of `brier_tracker` never crashes regardless of env_config availability (env_config errors surface inside the function's existing `try/except`, not at import time). Each call reflects the current `RUPPERT_ENV` at call time.

### What could go wrong

If `env_config` raises inside `_get_brier_paths()`, the caller's `try/except` will catch it and log a warning — same as any other exception in these functions. No data is written. No import-time crash.

Performance: `_get_brier_paths()` is called on every invocation of `log_prediction`, `score_prediction`, and `get_domain_brier_summary`. This is a path resolution plus one env_config call per trade event — negligible overhead.

---

## ISSUE-101 — brier_tracker.py: Duplicate scoring (revised)

### What to change

In `environments/demo/brier_tracker.py`, the `score_prediction()` function appends to `_SCORED_FILE` (now: the path returned by `_get_brier_paths()`) with no dedup check. If `score_prediction()` is called twice for the same ticker and date (e.g., settlement checker retries, or a duplicate settle event fires), two identical scored entries are written.

Add a dedup check before the append, keyed on `(ticker, date)`. The `date` is extracted from the prediction record's `ts` field (ISO timestamp, first 10 characters):

```python
# Dedup: skip if (ticker, date) already appears in scored file
prediction_date = str(prediction.get("ts", ""))[:10]  # "YYYY-MM-DD" from ISO timestamp
if _scored_file.exists():
    for existing_line in _scored_file.read_text(encoding="utf-8").strip().splitlines():
        try:
            existing_rec = json.loads(existing_line)
            if (existing_rec.get("ticker") == ticker
                    and str(existing_rec.get("resolved_at", ""))[:10] == prediction_date):
                logger.debug(
                    f"[Brier] Duplicate score suppressed for {ticker} "
                    f"on {prediction_date} — already in scored file"
                )
                return
        except Exception:
            continue

# (then proceed with the append)
_logs_dir.mkdir(exist_ok=True)
with open(_scored_file, "a", encoding="utf-8") as f:
    f.write(json.dumps(scored_entry) + "\n")
```

**Critical: the dedup check must NOT condition on `outcome is not None`.** Do not use:
```python
if existing_rec.get("outcome") is not None:  # WRONG — allows null-outcome records to bypass dedup
```

Dedup on key existence alone (`ticker + date` match). Rationale: a record with `outcome: null` in `_SCORED_FILE` represents a partial/corrupt write from a previous run. If dedup respects null outcomes, a second call for the same (ticker, date) would bypass the guard and write a duplicate. The correct behavior is: once a (ticker, date) key exists in `_SCORED_FILE` for any reason, block re-scoring.

Place the dedup block immediately after finding `prediction` (after the `if prediction is None: return` guard) and before computing `scored_entry`.

### Why (ticker, date) not ticker alone

The original spec used ticker-only dedup. Kalshi tickers are unique per contract expiry, making re-trading the same ticker across sessions uncommon — but not impossible. Any legitimate second trade session on the same ticker but a different date would be silently dropped with ticker-only dedup, with no log entry and no error. The missing scored prediction would understate domain Brier stats with no auditable trail.

`(ticker, date)` is the minimum safe key. It matches the processed-key scheme already used by `prediction_scorer.py`'s `_load_processed_keys()`, keeping both scoring paths consistent.

### What behavior changes

Before: every call to `score_prediction()` for an already-scored ticker appends another entry. Brier averages are inflated by duplicate entries weighted toward retried tickers. Domain counts are overcounted. Null-outcome records in the scored file are transparent to dedup and allow duplicates.

After: once a (ticker, date) key appears in `_SCORED_FILE`, subsequent calls for the same pair are suppressed with a debug log. Brier statistics reflect true trade counts. Null-outcome records block re-scoring the same key.

### What could go wrong

The dedup check reads all of `_SCORED_FILE` on every call. At small scale (hundreds of records) this is fine. At large scale (thousands of records) it becomes slow — but that's a performance concern, not a correctness concern, and can be addressed later with an in-memory set.

Apply this fix in the same commit as ISSUE-004. The path-resolution change must be in place for dedup to read the correct file.

---

## ISSUE-103 — prediction_scorer.py: Null predicted_prob for multi-day positions (revised)

### What to change

In `environments/demo/prediction_scorer.py`, the `score_new_settlements()` function builds a buy index keyed by `(ticker, date)`:

```python
buy_index: dict[tuple, dict] = {}
for rec in all_trades:
    action = rec.get('action', '')
    if action in ('buy', 'open'):
        key = (rec.get('ticker', ''), rec.get('date', ''))
        if key not in buy_index:
            buy_index[key] = rec
```

When scoring a settle record, it looks up the buy by the settle record's date. For overnight holds the settle date ≠ buy date, so the lookup misses and `buy_rec` is `{}`, making `predicted_prob = None`.

**Replace the ticker-only secondary index with a (ticker, side) secondary index.** The side must be read from the **settle record first**, falling back to an empty string if absent, so the fallback key is correct for the settle event being processed:

```python
# Primary index: (ticker, date) — exact match for same-day trades
buy_index: dict[tuple, dict] = {}
# Fallback index: (ticker, side) — for multi-day positions where settle date != buy date
# Keyed on side to prevent returning the wrong buy record when a ticker is re-traded from
# the opposite side on a different date. If (ticker, side) doesn't match, return None —
# do NOT fall through to a stale or wrong-side buy record.
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

Then change the buy record lookup from:

```python
buy_rec = buy_index.get(key, {})
```

to:

```python
settle_side = rec.get('side', 'yes')
buy_rec = buy_index.get(key) or buy_index_by_ticker_side.get((ticker, settle_side))
# If neither lookup succeeds, buy_rec is None.
# All subsequent buy_rec field accesses must use: buy_rec.get('field') if buy_rec else None
```

Update all downstream uses of `buy_rec` to handle `None` (not just `{}`). The existing `.get()` calls already handle missing keys; they just need to guard against `None` as the object:

```python
module = rec.get('module') or (buy_rec.get('module', '') if buy_rec else '')
# ... etc.
predicted_prob = buy_rec.get('noaa_prob') if buy_rec else None
if predicted_prob is None:
    predicted_prob = buy_rec.get('model_prob') if buy_rec else None
if predicted_prob is None:
    predicted_prob = buy_rec.get('market_prob') if buy_rec else None

side = rec.get('side') or (buy_rec.get('side', 'yes') if buy_rec else 'yes')
```

### Why (ticker, side) not ticker alone — critical impact

The ticker-only fallback introduced in the original spec has a specific failure mode that is **worse than returning null**:

The scorer applies a side-flip when the trade's `side == 'no'`:
```python
if side == 'no' and _outcome is not None:
    _outcome = 1 - _outcome
    if predicted_prob is not None:
        predicted_prob = round(1.0 - float(predicted_prob), 4)
```

`side` is resolved as: `rec.get('side') or buy_rec.get('side', 'yes')`.

If a ticker was previously traded YES on Day 1 and is now being scored for a NO trade settled on Day 4, a ticker-only fallback returns the Day 1 buy record (YES side). `buy_rec.get('side')` = `'yes'`. The combined side resolution is therefore `'yes'` for what should be a NO trade. The side-flip does **not** fire. The predicted_prob is used as-is (a YES-perspective probability applied to a NO outcome). The Brier score is computed incorrectly and written to `scored_predictions.jsonl` with no warning.

A wrong predicted_prob (a float) passes through `analyze_brier_score()` and corrupts the domain Brier average. A null predicted_prob is skipped by `analyze_brier_score()`. Wrong is worse than null.

**The (ticker, side) fallback eliminates this.** If a YES buy record exists but the settle is for a NO trade, the `(ticker, 'no')` key finds no match and `buy_rec = None`. `predicted_prob = None`. The Brier entry is written with `predicted_prob: null` and `brier_score: null`. `analyze_brier_score()` skips it. No corruption.

### Return null when no (ticker, side) match — spec the explicit behavior

If `buy_rec is None` after both lookups:
- `predicted_prob = None`
- `brier_score = None`
- Write the scored entry with `predicted_prob: null, brier_score: null`
- Do NOT attempt further fallbacks
- Do NOT default side to `'yes'` and proceed with a side-flip guess

The null entry occupies the processed-key slot, preventing re-scoring. This is correct: the settle event is real, the scoring happened, the buy record was simply unresolvable. Better to record a null than a corrupt float.

Add a warning log when the fallback path is used (whether it succeeds or not):

```python
if not buy_index.get(key):
    if buy_rec:
        logger.warning(
            f"[Scorer] {ticker}: date mismatch — using (ticker, side) fallback "
            f"buy record (buy date={buy_rec.get('date', '?')}, settle date={trade_date})"
        )
    else:
        logger.warning(
            f"[Scorer] {ticker}: no matching buy record found for "
            f"(ticker={ticker}, side={settle_side}) — predicted_prob will be null"
        )
```

### What behavior changes

Before: any overnight position where the settle date ≠ buy date produces `predicted_prob: null`. Any ticker re-traded from the opposite side uses the wrong buy record, produces a silently corrupted predicted_prob and Brier score.

After: overnight same-side positions use the `(ticker, side)` fallback and get a valid predicted_prob if a matching buy record exists. Opposite-side or unresolvable cases return null. A warning log is written in both fallback cases for audit. No corrupt Brier scores reach the scored file.

### What could go wrong

The `(ticker, side)` fallback stores the **first-seen** buy record for a ticker+side pair. For scale-in trades where the same ticker+side is bought multiple times at different prices, this uses the first leg's probability. That's acceptable for now — it's better than null and far better than a wrong-side corrupt float. ISSUE-050 (weighted average across scale-in legs) addresses this properly as a follow-up.

---

## ISSUE-041 — optimizer.py: analyze_daily_cap_utilization() double-counts closed trades

### What to change

In `agents/ruppert/strategist/optimizer.py`, the `analyze_daily_cap_utilization()` function sums `size_dollars` for every record in the enriched trades list:

```python
def analyze_daily_cap_utilization(trades: list):
    daily = defaultdict(float)
    for t in trades:
        ts = t.get("timestamp", "")
        size = t.get("size_dollars", 0.0)
        if not ts:
            continue
        try:
            date_str = str(ts)[:10]
            daily[date_str] += float(size) if size else 0.0
        except (ValueError, TypeError):
            pass
```

The `trades` list contains all records — including buy, exit, and settle records. Exit and settle records also have a `size_dollars` field (used there to hold the P&L value). Summing all records double-counts every closed trade: once as the original buy, and again as the exit/settle.

Add an action filter before summing:

```python
for t in trades:
    if t.get("action") not in ("buy", "open"):
        continue
    ts = t.get("timestamp", "")
    ...
```

This ensures only entry records (buys) contribute to the daily capital deployment total.

### What behavior changes

Before: every closed trade is counted twice. A $100 buy that settles at $0 shows up as $100 (buy) + $0 (settle, pnl=0) = $100, but a $100 buy that exits at $50 profit shows up as $100 (buy) + $50 (exit pnl) = $150. Cap utilization is overstated by an amount that depends on trade outcomes — it's both wrong and inconsistent.

After: only buy/open records are summed. Daily capital deployment reflects actual dollars committed, not dollars committed plus exit proceeds. Cap utilization percentages become meaningful.

### What could go wrong

This fix depends on ISSUE-005 being applied first. Without the path fix, `load_trades()` returns zero records and this function never runs on real data. Apply in sequence.

If any buy record is logged with `action='buy'` but the field contains a variant spelling (e.g., `'Buy'`, `'BUY'`), it would be excluded. Looking at `build_trade_entry()` in logger.py, the action normalization step already lowercases and strips to `'buy'`, so this is safe.

---

## ISSUE-046 — optimizer.py: analyze_exit_timing() — full fix (revised)

### Problem statement

In `agents/ruppert/strategist/optimizer.py`, `analyze_exit_timing()` attempts to compute hold time using:

```python
entry_ts = t.get("timestamp")
exit_ts = t.get("exit_timestamp")
```

The field `exit_timestamp` does not exist in the trade log schema. Exit/settle records have a single `timestamp` field: the time the exit/settle event was logged. There is no `exit_timestamp`. The result is that `exit_ts` is always `None`, `hold_times` is always empty, and `count` is always `len(hold_times) = 0`.

**The minimal fix is broken.** Even if `hold_times` is cleared and `avg_hold_hours` removed from the return dict, the `count` key in the return dict would still be `len(hold_times) = 0`. The `build_report()` function gates all exit timing output behind:

```python
et_count = exit_timing["count"]
if et_count == 0:
    lines.append("- No trades with exit data found (exit_price field absent).")
```

With `count = len(hold_times) = 0` always, the P&L average (which is computed correctly from the `pnl` field) is **also hidden** — the guard blocks the entire section. The minimal fix leaves P&L silently invisible even after ISSUE-005 is applied.

### Full fix

**Change 1: Signature of `analyze_exit_timing()`**

Add a `buy_index` parameter (dict of ticker → buy record) so the function can look up entry timestamps for exit/settle records:

```python
def analyze_exit_timing(trades: list, buy_index: dict = None):
    """
    Returns {avg_hold_hours, avg_pnl, count} for trades with exit_price.

    Args:
        trades:     Enriched trades list (all records including buys, exits, settles).
        buy_index:  Dict of ticker -> buy record, for computing hold time.
                    If None or a ticker has no buy record, hold time is skipped for that
                    record but P&L is still counted. Build from buy/open records only.
    """
    if buy_index is None:
        buy_index = {}
    hold_times = []
    pnls = []
    for t in trades:
        if "exit_price" not in t or t["exit_price"] is None:
            continue

        # exit_ts: the timestamp on the exit/settle record IS the exit time
        exit_ts_str = t.get("timestamp")
        ticker = t.get("ticker", "")

        # entry_ts: comes from the matching buy record, looked up by ticker
        buy_rec = buy_index.get(ticker)
        entry_ts_str = buy_rec.get("timestamp") if buy_rec else None

        if entry_ts_str and exit_ts_str:
            try:
                entry_dt = datetime.fromisoformat(str(entry_ts_str)[:19])
                exit_dt = datetime.fromisoformat(str(exit_ts_str)[:19])
                hold_hours = (exit_dt - entry_dt).total_seconds() / 3600
                hold_times.append(hold_hours)
            except (ValueError, TypeError):
                pass

        # P&L: pnl field is present and correct on exit/settle records
        pnl = t.get("pnl") if t.get("pnl") is not None else t.get("realized_pnl")
        if pnl is not None:
            try:
                pnls.append(float(pnl))
            except (ValueError, TypeError):
                pass

    return {
        "count": len(pnls),          # KEY FIX: was len(hold_times) — now len(pnls)
        "avg_hold_hours": statistics.mean(hold_times) if hold_times else None,
        "avg_pnl": statistics.mean(pnls) if pnls else None,
    }
```

**Why `count = len(pnls)` and not `len(hold_times)`:**

`build_report()` uses `count` to decide whether to show the exit timing section at all. Hold times require a matching buy record; P&L does not. A settle record with no matching buy record still has a valid P&L. Using `len(pnls)` ensures the section is shown whenever there are settled trades, regardless of whether buy/exit correlation succeeded for hold time. `avg_hold_hours` can be `None` even when `count > 0` — `build_report()` already handles this gracefully with the `if avg_hold is not None:` guard.

**Change 2: Build buy index in `main()` before calling `analyze_exit_timing()`**

In `main()`, after enriching trades but before the analysis calls, build the buy index:

```python
# Build buy record index keyed by ticker — used by analyze_exit_timing for hold time computation
buy_index_for_exits = {}
for t in trades:
    if t.get("action") in ("buy", "open"):
        ticker = t.get("ticker", "")
        if ticker and ticker not in buy_index_for_exits:
            buy_index_for_exits[ticker] = t

# ...

# 3. Exit timing (pass buy index for hold time computation)
exit_timing = analyze_exit_timing(trades, buy_index_for_exits)
```

**Change 3: No changes needed to `build_report()`**

`build_report()` already handles `avg_hold_hours = None` correctly with `if avg_hold is not None:`. With `count = len(pnls)`, the `if et_count == 0` guard will only fire when there are truly no exit/settle records — which is correct for dry-run mode. When exits exist, the section will display avg P&L and avg hold time (if computable).

### What behavior changes

Before: `exit_ts` is always `None`. `hold_times` is always empty. `count` = `len(hold_times)` = 0. `build_report()` always prints "No trades with exit data found" and hides all P&L data, even when exit records exist with valid `pnl` values.

After:
- `count = len(pnls)` — section displays whenever settled trades exist
- `avg_pnl` — computed and displayed from the `pnl` field on exit/settle records
- `avg_hold_hours` — computed for exits where a matching buy record exists; `None` for orphaned exits
- If buy record for a ticker is not found, hold time is skipped for that record, but P&L still counted

### What could go wrong

If the same ticker was bought multiple times (scale-in), `buy_index_for_exits` stores only the first buy record's timestamp. Hold time for subsequent exit legs will be measured from the first buy, which overstates hold time for scale-in positions. This is acceptable for now — ISSUE-050 handles scale-in correctly as a follow-up.

Exit records with no matching buy record (orphaned — e.g., manual corrections) will have `avg_hold_hours` contribution skipped but their P&L will still be counted. This is correct behavior.

This fix depends on ISSUE-005 being applied first for the same reason as ISSUE-041.

---

## Sequencing

Apply in this order:

1. **ISSUE-005** — path fix first; all other optimizer issues are meaningless without it
2. **ISSUE-004 + ISSUE-101** — apply together in one commit to brier_tracker.py
3. **ISSUE-103** — independent; can be applied in parallel with brier_tracker fixes
4. **ISSUE-041** — after ISSUE-005
5. **ISSUE-046** — after ISSUE-005

QA validation for each:
- **ISSUE-005**: run optimizer manually after fix, confirm it prints non-zero trade count
- **ISSUE-004**: verify `predictions.jsonl` and `scored_predictions.jsonl` appear in the correct env logs directory; confirm importing brier_tracker does not crash even if env_config is patched to fail
- **ISSUE-101**: call `score_prediction()` twice for the same ticker on the same date; confirm only one entry in `_SCORED_FILE`; also call for the same ticker on two different dates; confirm both entries appear
- **ISSUE-101** (null-outcome case): manually insert a `(ticker, date)` record with `outcome: null` into `_SCORED_FILE`; call `score_prediction()` for that ticker; confirm it is blocked (not duplicated)
- **ISSUE-103**: find a settle record with a date different from its buy record's date, same side — confirm the scored entry has a non-null `predicted_prob`; find a ticker traded YES on day 1 and re-settled as NO on day 4 — confirm the NO settlement gets `predicted_prob: null`, not a flipped YES probability
- **ISSUE-041**: run cap utilization analysis on a day with known exits; confirm daily total matches sum of buy sizes only
- **ISSUE-046**: run exit timing analysis after ISSUE-005; confirm section shows P&L average and trade count, not "No trades with exit data found"

---

_End of Sprint 3 Spec (Revised). Data Scientist._
