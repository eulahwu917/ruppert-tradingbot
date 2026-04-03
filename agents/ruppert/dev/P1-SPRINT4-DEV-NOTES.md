# P1-SPRINT4-DEV-NOTES.md — Sprint P1-4 Dashboard Fixes
**Dev:** Developer subagent  
**Sprint:** P1-4  
**File:** `environments/demo/dashboard/api.py`  
**Spec:** `agents/ruppert/data_scientist/specs/P1-SPRINT4-SPEC.md`

---

## Batch 1 — Crash Fixes (ISSUE-018 + ISSUE-019)

**Status:** Implemented ✅ | QA pending

### ISSUE-018 — `/api/account` NameError on `AUTO_SOURCES` / `MANUAL_SOURCES`

**Root cause:** Return dict referenced `AUTO_SOURCES` and `MANUAL_SOURCES` which were never defined. The function already had `_is_auto()` and `_is_manual()` closures using `AUTO_PREFIXES`/`MANUAL_PREFIXES` with prefix matching.

**Fix applied:**
```python
# Before (crashing):
"bot_trade_count":    len([t for t in trades if t.get('source','bot') in AUTO_SOURCES]),
"manual_trade_count": len([t for t in trades if t.get('source','bot') in MANUAL_SOURCES]),

# After (correct):
"bot_trade_count":    len([t for t in trades if _is_auto(t.get('source', 'bot'))]),
"manual_trade_count": len([t for t in trades if _is_manual(t.get('source', 'bot'))]),  # ISSUE-018
```

**Behavior change:** Endpoint goes from 500 crash → returns correct counts. Prefix-matching logic (`ws_*` sources counted as bot) is intentional and already used in the deployed capital calculation above.

---

### ISSUE-019 — `/api/positions/active` side used before assigned

**Root cause:** In the DEMO-mode loop over `open_trades`, `_parse_crypto_band_title(ticker, side)` was called before `side = t.get('side', 'no')`. On first iteration: `UnboundLocalError`. On subsequent iterations: iteration bleed (previous trade's `side` used).

**Fix applied:** Moved `side = t.get('side', 'no')` to be the **absolute first line** in the loop body, before all other `t.get(...)` reads. Also removed the now-redundant second `side =` assignment that was below `title = raw_title`.

```python
# Before:
for t in open_trades:
    ticker = t.get('ticker', '')
    raw_title = (t.get('title') or ticker).replace('**', '')
    _band_title = _parse_crypto_band_title(ticker, side)   # ← crash/bleed
    ...
    title  = raw_title
    side   = t.get('side', 'no')                           # ← too late
    source = t.get('source', 'bot')

# After:
for t in open_trades:
    side   = t.get('side', 'no')                           # FIRST
    ticker = t.get('ticker', '')
    raw_title = (t.get('title') or ticker).replace('**', '')
    _band_title = _parse_crypto_band_title(ticker, side)   # ← now safe
    ...
    title  = raw_title
    source = t.get('source', 'bot')                        # ← side removed here (already set above)
```

**Behavior change:** Endpoint goes from crash → returns correct open positions with correct band titles.

---

## Batch 2 — Data Correctness (ISSUE-063 + ISSUE-064 + ISSUE-065 + ISSUE-066)

**Status:** Implemented ✅ | QA pending

### ISSUE-063 — P&L chart hardcodes `"2026-03-10"`

**Root cause:** `get_pnl_history()` built the chart `points` list with a single hardcoded `"2026-03-10"` data point representing all prior closed P&L.

**Fix applied:** Accumulated a `pnl_by_day` dict during the settled_tickers loop (BOT-only), replacing the hardcoded points block with per-day data sorted by date. Today's point replaces or updates the closed-only entry with the combined closed+open total.

**Note:** Chart will not render until frontend implements `renderPnlChart` — frontend is not wired up per DS investigation. The backend change is safe to ship.

---

### ISSUE-064 — `BOT_SRC` tuple misses `ws_*` and `crypto_15m` sources

**Root cause:** `BOT_SRC = ('bot','weather','crypto')` used flat equality — `ws_position_tracker` and `crypto_15m` trades not counted in `bot_dep`.

**Fix applied:**
- Added `_is_auto()` and `_is_manual()` as **module-level** functions (promoted from `get_account()` where they were closures)
- Replaced `BOT_SRC`/`MAN_SRC` tuple equality in `get_pnl_history()` with `_is_auto()`/`_is_manual()` calls
- `get_account()` closures now call the module-level functions (backward compatible, prefix logic unchanged)

**Known gap:** `_build_state()` computes `deployed` as `sum(p['cost'] for p in positions)` with no source filter — structural inconsistency pre-dates this sprint and is NOT addressed here.

---

### ISSUE-065 — Settled positions appear open in `_build_state()`

**Root cause:** `exited` set was built from `exit_records` (exit-only), so `action='settle'` records were not filtering positions. Settled positions leaked into `open_pos_tickers`.

**Fix applied:**
- `exited` set now includes both `exit` AND `settle` actions (set comprehension, not from `exit_records`)
- `exit_records` dict remains **exit-only** (used for P&L lookup — must not include settle records)

**Two variables kept separate:**
- `exited` = filtering set (exit OR settle)
- `exit_records` = P&L lookup dict (exit ONLY)

---

### ISSUE-066 — `closed_win_rate` deduplicates on ticker instead of `trade_id`

**Root cause:** `bot_wins` and `closed_count_by_source['bot']` were computed inside `settled_tickers.items()` loop — one entry per unique ticker. Multiple close records for same ticker collapsed to one.

**Fix applied:** Built `_close_records_by_id` dict (keyed by `trade_id` or fallback `(ticker, side)`) from all settle/exit records in `all_trades`. Computed `bot_wins` and `closed_count_by_source['bot']` by iterating this dict's values instead.

**Fallback chain:**
1. `trade_id` (or `id` field) → primary key
2. `(ticker, side)` composite → fallback if no trade_id
3. Skip record entirely if neither exists

**Expected behavior:** `total_trades` / `bot_trades` counts will increase (no longer artificially low due to ticker dedup). Not a regression.

---

## Batch 3 — Exception Handling (ISSUE-072)

**Status:** Implemented ✅ | QA pending

### Changes made

1. Added module-level logger at top of module:
   ```python
   import logging as _log
   _logger = _log.getLogger(__name__)
   ```

2. `_cache_reload_loop()` — wrapped `market_cache.load()` in try/except with `_logger.error` + `push_alert` fallback. Thread does NOT re-raise — keeps looping.

3. **Group A (ERROR)** — 6 high-severity `except Exception: pass` blocks in P&L/position loops replaced with `_logger.error("[dashboard:func] %s", e, exc_info=True)`

4. **Group B (WARNING)** — 5 medium-severity JSON parse errors in `read_*` functions: bare `except:` → `except Exception as e:` + `_logger.warning("[dashboard] JSON parse error in %s: %s", ...)`

5. **Group C (WARNING/DEBUG)** — 9 low-severity optional cache/enrichment blocks: added `_logger.warning(...)` or `_logger.debug(...)` as appropriate per spec groupings

### Spec notes / observations
- `push_alert` may not be in scope — added inner try/except so alert failure does not kill the cache loop. If `push_alert` is unavailable at runtime, the outer error is already logged.
- `get_deposits()` had bare `except: pass` (Group B) — fixed to `except Exception as e:` + warning.
- Total bare `except:` → `except Exception:` conversions: confirmed throughout Groups B and C.

---

## Post-Implementation Checks

**Syntax check:** `python -m py_compile dashboard/api.py` → OK  
**QA self-test:** 33/33 PASS  
**Config audit:** PASS WITH WARNINGS (6 pre-existing Task Scheduler warnings — not caused by this sprint)

**Files changed:**
- `environments/demo/dashboard/api.py` — all 3 batches implemented

**NOT committed** — awaiting QA clearance per pipeline rules.
