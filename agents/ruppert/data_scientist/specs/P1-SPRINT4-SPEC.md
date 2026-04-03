# P1-SPRINT4-SPEC.md — Dashboard Fixes
**Sprint:** P1-4  
**Author:** Data Scientist  
**Date:** 2026-04-03  
**Revised:** 2026-04-03 (post adversarial review)  
**Scope:** `environments/demo/dashboard/api.py` bug fixes only  
**Issues:** ISSUE-018, ISSUE-019, ISSUE-063, ISSUE-064, ISSUE-065, ISSUE-066, ISSUE-072

---

## Revision Summary (2026-04-03)

Six issues required spec revisions after adversarial code review. Changes by issue:

| Issue | What Changed |
|-------|-------------|
| 019 | Added explicit ordering rule: `side` must be the **first** read from `t` in the loop body. Added iteration bleed risk note. |
| 063 | **UNBLOCKED.** DS investigated frontend. `renderPnlChart` is not defined; chart is unimplemented. `points[]` is not consumed. Backend should return **per-day values**. Frontend engineer must also wire up `_pnlData` when chart is built. |
| 064 | Added known-gap note: `_build_state()` computes deployed capital differently (no source filter). Structural inconsistency between `/api/pnl` and `/api/state` deployed capital is pre-existing and NOT addressed by this fix. |
| 065 | Explicitly distinguished `exited` set (filtering open positions — add `settle` here) from `exit_records` dict (P&L lookup — exit only, do NOT add `settle` here). Two separate variables, two separate purposes. |
| 066 | Added expected behavior note: `total_trades` and `bot_trades` counts will increase after this fix (currently undercounted due to ticker dedup). Not a regression. Clarified `(ticker, side)` composite key fallback and skip-on-no-match behavior. |
| 072 | Added `_cache_reload_loop()` to scope — it has zero exception handling and its thread can die silently. Changed bare `except:` to `except Exception:` throughout. |

---

## ISSUE-018 — `/api/account` crashes with NameError: `AUTO_SOURCES` / `MANUAL_SOURCES` undefined

### Where
`get_account()` return statement, near the bottom of the function:
```python
"bot_trade_count":    len([t for t in trades if t.get('source','bot') in AUTO_SOURCES]),
"manual_trade_count": len([t for t in trades if t.get('source','bot') in MANUAL_SOURCES]),
```

### What's Wrong
The function defines `AUTO_PREFIXES` and `MANUAL_PREFIXES` (tuples), and helper closures `_is_auto()` / `_is_manual()` that use prefix matching. But the return statement references `AUTO_SOURCES` and `MANUAL_SOURCES` — names that are never defined anywhere in the function or module. This is a NameError that crashes the endpoint on every call.

### Fix
Replace the two broken list comprehensions in the return dict with the existing helper functions:

```python
"bot_trade_count":    len([t for t in trades if _is_auto(t.get('source', 'bot'))]),
"manual_trade_count": len([t for t in trades if _is_manual(t.get('source', 'bot'))]),
```

### Behavior Change
`/api/account` goes from crashing (500 error) to returning correct bot/manual trade counts. The counts will be slightly different from what a simple `in` check on a flat tuple would produce, because `_is_auto` uses prefix matching (e.g., `ws_*` sources are now included in bot count). That's intentional and correct.

### What Could Go Wrong
None — this is a straightforward name fix. The prefix-matching logic in `_is_auto`/`_is_manual` is already tested by the deployed capital calculation above the return statement.

---

## ISSUE-019 — `/api/positions/active` crashes: `side` used before assigned

### Where
`get_active_positions()`, in the DEMO-mode loop over `open_trades`, approximately lines:

```python
for t in open_trades:
    ticker = t.get('ticker', '')
    raw_title = (t.get('title') or ticker).replace('**', '')
    _band_title = _parse_crypto_band_title(ticker, side)   # ← `side` used HERE
    if _band_title:
        raw_title = _band_title
    _win_time = _parse_15m_window_time(ticker)
    ...
    title  = raw_title
    side   = t.get('side', 'no')                           # ← `side` assigned HERE (too late)
```

`_parse_crypto_band_title(ticker, side)` is called before `side` is read from the trade record. On the first iteration this raises `UnboundLocalError: local variable 'side' referenced before assignment`.

### Fix
Move the `side` assignment to be the **first read from `t`** in the loop body — before any other variable that depends on `side`:

```python
for t in open_trades:
    side   = t.get('side', 'no')                           # ← MUST be first read from t
    ticker = t.get('ticker', '')
    raw_title = (t.get('title') or ticker).replace('**', '')
    _band_title = _parse_crypto_band_title(ticker, side)
    ...
```

**Ordering rule (explicit):** `side = t.get('side', 'no')` must appear BEFORE any call that uses `side` in the loop body — specifically before `_parse_crypto_band_title(ticker, side)` AND before `_translate_15m_side(ticker, side)` (called later in `positions.append()`). The safest position is the absolute first line of the loop body, before all other `t.get(...)` reads.

### Iteration Bleed Risk
If `side` is moved but not placed at the top of the loop body — or if it's accidentally left lower in the loop than `_parse_crypto_band_title` — then on iteration N, `side` will carry over from iteration N-1. This means `_parse_crypto_band_title` will receive the previous trade's side value, silently producing wrong title transformations for crypto band positions.

This is a **placement-sensitive** fix. Dev should verify after the change that `side = t.get('side', 'no')` is the first executable statement inside the `for t in open_trades:` loop, not just moved to somewhere-above-the-call.

### Behavior Change
`/api/positions/active` goes from crashing on every call to returning the correct list of open positions. The band title logic already works correctly in `_build_state()` (which assigns `side` first) — this fix makes `get_active_positions()` consistent with it.

### What Could Go Wrong
None — `side` defaults to `'no'` which is the same default used everywhere else. Empty `open_trades` list returns `[]` before entering the loop.

---

## ISSUE-063 — P&L chart hardcodes `"2026-03-10"` as a historical data point

### Frontend Investigation (UNBLOCKED)

DS reviewed `environments/demo/dashboard/templates/index.html` before writing this spec.

**Findings:**
- `renderPnlChart` is called in `setPnlFrame()` but is **not defined anywhere** in the frontend — calling it would throw `ReferenceError: renderPnlChart is not defined`.
- `window._pnlData` is referenced in `setPnlFrame(window._pnlData || [])` but is **never populated** from any API call. `loadClosedPnl()` fetches `/api/pnl` but does not assign `pnl.points` to `window._pnlData`.
- The HTML section labeled `<!-- P&L Chart -->` in the layout is an **empty placeholder** — no `<canvas>`, no `<svg>`, no chart element exists yet.

**Conclusion:** The P&L chart is **not implemented** in the frontend. The `points[]` array from `/api/pnl` is not consumed by any rendering code. The fix to the backend chart data is safe to ship, but the chart will not become visible until the frontend engineer implements `renderPnlChart` and wires up `_pnlData`.

**Format decision:** Backend should return **per-day values** (each point = that day's P&L delta, not a running total). Rationale:
- Per-day is the natural output from trade logs and easier to validate.
- A frontend chart can cumulate per-day values to show a curve, or plot them as bars to show daily performance.
- Pre-cumulated values from the backend cannot easily be decomposed into daily deltas if the frontend wants to show bars.

**Frontend engineer action required (not in this Dev ticket):** To make the chart visible, the frontend must:
1. Add `window._pnlData = pnl.points || []` inside `loadClosedPnl()` after the `pnl` fetch.
2. Implement `function renderPnlChart(points) { ... }` using the array of `{date, pnl}` objects.
3. Add a chart element (canvas, SVG, or div) in the `<!-- P&L Chart -->` HTML section.

---

### Where (backend)
`get_pnl_history()`, near the bottom, in the chart `points` list construction:

```python
points = []
bot_closed_pnl = closed_by_source['bot']
# Day 1: bot-only closed P&L (settled trades from prior days)
if bot_closed_pnl != 0:
    points.append({"date": "2026-03-10", "pnl": round(bot_closed_pnl, 2)})
# Today: total bot (closed + open)
points.append({"date": today, "pnl": round(total_pnl, 2)})
```

The hardcoded `"2026-03-10"` date was a placeholder for "all prior closed P&L" as a single lump-sum point. It doesn't represent real trade data.

### Fix
Build the `points` list from actual trade log data — one point per calendar day with settled/exited trades. Use the same timestamp-parsing logic already present in the function (the `sdate` derivation in the settled-tickers loop).

Concretely:

1. During the `settled_tickers` loop that already runs above, accumulate a dict `pnl_by_day: dict[str, float]` keyed by ISO date string, adding each trade's pnl to the appropriate day. BOT-only (exclude trades matching `_is_manual`).
2. After the loop, replace the hardcoded `points` block with:
   ```python
   points = [{"date": d, "pnl": round(v, 2)} for d, v in sorted(pnl_by_day.items())]
   # Append today's total (closed + open) if not already present
   if today not in pnl_by_day:
       points.append({"date": today, "pnl": round(total_pnl, 2)})
   else:
       # Replace today's closed-only point with closed+open total
       for p in points:
           if p["date"] == today:
               p["pnl"] = round(total_pnl, 2)
   ```
3. Each point's `pnl` value is the **per-day P&L delta** for that day (not a running total). The frontend is responsible for cumulating if it wants to display a curve.

### Note on Today's Data Point
Today's point combines closed + open P&L (via `total_pnl`), while all prior days are closed-only. This creates a structural break at the rightmost point: prior days show settled P&L only; today shows settled + unrealized. This is intentional (we want today's live total) but means the chart curve will have a jump at today if open positions have significant unrealized value. Dev should be aware of this — it is not a bug.

### Behavior Change
The P&L chart `points` array will contain real daily data points instead of a single lump sum pinned to a stale date. The chart will become more granular as more days of data accumulate.

### What Could Go Wrong
- If the `sdate` parse fails for a trade (no timestamp, unparseable ticker), that trade's P&L won't appear in any day bucket. Acceptable — same fallback behavior as today.
- Exit-correction records should also be bucketed by day. The correction loop already runs separately — Dev should add correction pnl to `pnl_by_day` there as well (optional enhancement).
- The chart won't actually render until the frontend is implemented (see Frontend Investigation above).

---

## ISSUE-064 — `BOT_SRC` tuple missing `ws_*` source labels

### Where
`get_pnl_history()`, near the bottom of the function:

```python
BOT_SRC = ('bot','weather','crypto')
MAN_SRC = ('economics','geo','manual')
bot_dep = sum(t.get('size_dollars',0) for t in open_t if t.get('source','bot') in BOT_SRC)
man_dep = sum(t.get('size_dollars',0) for t in open_t if t.get('source','bot') in MAN_SRC)
```

### What's Wrong
`BOT_SRC` is a flat equality tuple — sources must match exactly. The trade logs contain at least one `ws_*` source label (`ws_position_tracker`) that is not in this tuple. Trades from that source are counted in neither `bot_dep` nor `man_dep`, making them invisible to the capital tracker. `crypto_15m` is also absent from `BOT_SRC` and is present in trade logs.

### Actual ws_* source labels in trade logs (as of 2026-04-03)
- `ws_position_tracker`

### Fix
Expand `BOT_SRC` to include all known bot/autonomous source labels:

```python
BOT_SRC = ('bot', 'weather', 'crypto', 'crypto_15m', 'ws_position_tracker')
```

Or, preferably, replace the tuple equality check with the same `_is_auto()` prefix-matching helper already defined in `get_account()`. Move `_is_auto` / `_is_manual` to module scope (or a shared helper file) so both endpoints use the same logic:

```python
bot_dep = sum(t.get('size_dollars',0) for t in open_t if _is_auto(t.get('source','bot')))
man_dep = sum(t.get('size_dollars',0) for t in open_t if _is_manual(t.get('source','bot')))
```

The prefix-match approach is preferred because it handles new `ws_*` sources automatically without needing another spec.

### Behavior Change
`bot_dep` (bot-deployed capital) increases to include WS-originated trades. This fixes the capital utilization display — trades from `ws_position_tracker` will now appear in the deployed capital sum.

### Known Gap — Structural Inconsistency with `/api/state` Deployed Capital

**This fix does NOT address a pre-existing structural inconsistency:**

`_build_state()` computes deployed capital differently:
```python
deployed = round(sum(p['cost'] for p in positions), 2)
```
This sums ALL position costs with no source filter — it does not distinguish bot vs manual, and does not use `BOT_SRC`/`_is_auto()` at all.

After this fix, `/api/pnl` will report `bot_dep` using prefix-filtered source matching, while `/api/state` will report `deployed` as a total across all sources. These two values are architecturally inconsistent: one is source-filtered, the other is all-position. A user comparing `bot_dep` from `/api/pnl` with `deployed` from `/api/state` will see different numbers for the same underlying positions.

**This is a known gap, not a regression introduced by this fix.** The inconsistency pre-dates this sprint. Closing it would require a separate spec that either: (a) adds source filtering to `_build_state()`, or (b) removes source filtering from `get_pnl_history()` to match `_build_state()`. That decision is out of scope here.

### What Could Go Wrong
- If `ds_no_side_audit_*`-prefixed sources appear in trade logs (audit correction records), they would not match either `_is_auto` or `_is_manual`. They should be excluded from deployed capital entirely — confirm with Dev that the prefix logic in `get_account()` is already correct for this case (it is, since `ds_*` doesn't start with any AUTO_PREFIXES or MANUAL_PREFIXES).
- `settlement_checker` and `pnl_correction_script` are also in the trade logs. These are not real open positions — they generate settle/exit/correction records, not buy records. They will never appear in `open_t` (which filters to non-exited, non-settled, action=open/buy records), so they don't need special handling here.

---

## ISSUE-065 — Settled positions appear open in `_build_state()`

### Where
`_build_state()`, in the `exited` set construction and the `open_pos_tickers` loop:

```python
# This only tracks action='exit', not action='settle'
exit_records: dict = {}
for t in all_trades:
    if t.get('action') == 'exit':
        tk = t.get('ticker', '')
        if tk:
            exit_records[tk] = t

# ...later...
exited: set = set(exit_records.keys())   # ← only exit records, settle records excluded

for t in all_trades:
    ticker = t.get('ticker', '')
    if not ticker or ticker in seen2 or ticker in exited:  # ← settled tickers pass through here
        continue
    action = (t.get('action') or '').lower()
    if action != 'open' and not action.startswith('buy'):
        continue
    ...
    open_pos_tickers[ticker] = t           # ← settled positions added as "open"
```

Note: `get_active_positions()` correctly checks `action in ('exit', 'settle')`, but `_build_state()` (which drives `/api/state`) does not.

### Fix — Two Variables, Two Purposes (Dev Must Keep These Separate)

There are **two distinct variables** in `_build_state()` with different purposes. This fix changes only ONE of them:

**Variable 1: `exited` set** — used to filter open positions (determines which tickers are treated as "still open"). This is what is broken: it excludes `settle` records.

**Fix:** Change the `exited` set construction to include both `exit` AND `settle` actions:

```python
exited: set = {
    t.get('ticker')
    for t in all_trades
    if t.get('action') in ('exit', 'settle') and t.get('ticker')
}
```

**Variable 2: `exit_records` dict** — used later in `_build_state()` for P&L lookup when computing realized P&L for closed positions:
```python
elif ticker in exit_records:
    ex = exit_records[ticker]
    pnl_val = ex.get('pnl')
```
This dict must remain **exit-only**. Do NOT add `settle` records to `exit_records`. Settled positions have their P&L computed through a separate `settled_tickers` path — adding settle records to `exit_records` would break P&L lookups for manually-exited positions by overwriting exit records with settle records.

**Summary:**
- `exited` set → include `exit` AND `settle` → gates which tickers appear in `open_pos_tickers`
- `exit_records` dict → include `exit` ONLY → used for P&L value lookup on manually-exited positions

Dev must not unify or conflate these two variables. They exist for different reasons.

### Behavior Change
Settled positions will no longer appear in the open positions list returned by `/api/state`. The positions count will drop by however many settled positions currently leak through. Capital deployed will also decrease accordingly.

### What Could Go Wrong
- If `is_settled_ticker()` already catches most stale tickers, the visible bug may be small in practice. This fix is still correct — it closes the gap for same-day settle records where `is_settled_ticker()` returns False.
- No risk of over-filtering: a ticker in `exited` means we have explicit confirmation (a log record) that it was settled or exited. That's definitive.

---

## ISSUE-066 — `closed_win_rate` uses ticker dedup instead of `trade_id`

### Where
`get_pnl_history()`. The win rate is computed from counters accumulated in the `settled_tickers` loop:

```python
# settled_tickers is keyed by ticker (one entry per unique ticker)
for ticker, t in settled_tickers.items():
    ...
    if pnl > 0: closed_wins += 1
    ...
    if pnl > 0:
        bot_wins += 1
    ...
    closed_count_by_source['bot'] += 1

# Then:
"closed_win_rate": round(bot_wins / closed_count_by_source['bot'] * 100, 1) if ...
```

`settled_tickers` is a dict keyed by ticker (one entry per unique ticker, using the first `open`/`buy` record seen). If there are multiple close records for the same ticker (scale-in trades with multiple partial closes, or duplicate settle records), they're all collapsed to a single entry.

### Fix
Change the win rate calculation to iterate over close records (settle/exit records) keyed by `trade_id`, not open records keyed by ticker.

Concretely:
1. Build a `close_records_by_trade_id` dict during the `close_records_pnl` construction pass:
   ```python
   close_records_by_trade_id = {}
   for t in all_trades:
       if t.get('action') in ('exit', 'settle'):
           trade_id = t.get('trade_id') or t.get('id')
           if trade_id:
               close_records_by_trade_id[trade_id] = t
           else:
               # Fallback for records missing trade_id: use (ticker, side) as composite key
               fallback_key = (t.get('ticker', ''), t.get('side', ''))
               if fallback_key[0]:  # only if ticker exists
                   close_records_by_trade_id[fallback_key] = t
   ```
2. Compute `bot_wins` and `closed_count_by_source['bot']` by iterating `close_records_by_trade_id.values()` instead of `settled_tickers.items()`.
3. Exclude manual sources from the bot win rate the same way the existing loop does.

### Fallback Behavior for Missing `trade_id`

If a close record has no `trade_id` (older log entries before trade_id was added):
- **Fallback:** use `(ticker, side)` as a composite key. This is still imperfect for scale-in trades but is better than the current ticker-only key.
- **If even `(ticker, side)` doesn't match** (missing ticker or ambiguous): **skip the record** — do not add a phantom entry to the denominator. It is better to under-count slightly than to corrupt the win rate with mismatched data.
- Do not raise or log an error for missing trade_ids on older records — this is expected for historical data.

### Expected Behavior After Fix (Not a Regression)

After this fix, `total_trades` and `bot_trades` counts in the `/api/pnl` response **will increase**. Currently these fields are populated from `closed_count_by_source['bot']` which is incremented once per unique ticker. After the fix, it will be incremented once per close record (settle/exit). If the same ticker was closed twice (scale-in with two partial exits, or a re-entry), the count will be 2 instead of 1.

**This is expected and correct behavior, not a regression.** The old count was wrong (artificially low due to ticker dedup). The new count accurately reflects the number of closed trade events.

David should be informed that trade counts may jump after this fix is deployed. Example: if there were 8 unique tickers but 12 close records, the count goes from 8 to 12. This is accurate.

### Behavior Change
Win rate becomes more accurate when the same ticker has multiple settle records (scale-ins, partial closes). The count will be higher than before. The absolute number change depends on how many multi-close positions exist in the logs.

### What Could Go Wrong
- The existing total P&L calculation is not affected by this change (it already uses pnl from close records).
- Module-level win rates (inside `modules_out`) are already computed correctly via `compute_module_closed_stats_from_logs()` which iterates close records directly. Only the top-level `closed_win_rate` is wrong in the current code.

---

## ISSUE-072 — 19+ silent exception swallows in dashboard API

### Approach

Group by severity. The high-severity swallows (P&L loops, position-building loops) should log at ERROR level so bugs surface. The low-severity swallows (cache misses, optional enrichment) should log at WARNING or DEBUG. None should be bare `pass` in production — at minimum they should emit a single log line so we know something failed.

**Implementation pattern:**
```python
import logging as _log
_logger = _log.getLogger(__name__)

# High severity (replace bare pass):
except Exception as e:
    _logger.error("[dashboard] %s failed: %s", context_label, e, exc_info=True)

# Low severity (cache miss, optional data):
except Exception as e:
    _logger.warning("[dashboard] %s: %s", context_label, e)
```

Add `import logging as _log` and `_logger = _log.getLogger(__name__)` **once at module level** — not inside any function. The file already has `import logging as _logging` inside `startup_load_cache()` as a function-local import; that is separate and does not create a module-level logger. Dev must add module-level logger separately.

### Bare `except:` → `except Exception:` (REQUIRED Throughout)

All bare `except:` blocks (no exception type) must be changed to `except Exception:`. Bare `except:` catches `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit` in addition to normal exceptions — this is almost never correct and can suppress shutdown signals. Groups B and C below contain bare `except:` blocks that must be fixed.

---

### Scope Addition: `_cache_reload_loop()`

**This function was not in the original spec but must be included in this fix.**

Current code:
```python
def _cache_reload_loop() -> None:
    while True:
        _time.sleep(60)
        market_cache.load()
```

This function has **zero exception handling**. It runs in a background daemon thread that continuously updates the market price cache (used for open position P&L calculations). If `market_cache.load()` throws any exception:
- The thread dies silently with no log output.
- The price cache stops updating permanently for the remainder of the session.
- All open position P&L calculations go stale — they continue to display but show prices from the last successful load, with no indication that prices are stale.
- This failure mode is **higher severity than most Group A items** because it silently corrupts live P&L for ALL open positions, not just one trade record.

**Fix:**
```python
def _cache_reload_loop() -> None:
    while True:
        _time.sleep(60)
        try:
            market_cache.load()
        except Exception as e:
            _logger.error("[dashboard] _cache_reload_loop: market_cache.load() failed — "
                          "price cache is stale: %s", e, exc_info=True)
            # Push alert so dashboard operator knows prices may be wrong
            try:
                push_alert("price_cache_failure",
                           f"market_cache.load() failed: {e}",
                           level="warning")
            except Exception:
                pass  # Don't let alert failure kill the loop
            # Do NOT re-raise — keep the loop alive so it retries next cycle
```

The loop must NOT re-raise after a load failure — the retry on the next 60-second cycle is the recovery mechanism. Logging the error is sufficient to make the failure visible. If `push_alert` is not available in scope, replace with an additional `_logger.error` call.

---

### Location List

All locations in `environments/demo/dashboard/api.py`:

**Group A — HIGH SEVERITY (P&L / positions / trade data loops — errors here corrupt dashboard numbers)**

1. **`compute_module_closed_stats_from_logs()`** — `except Exception: pass` in the per-trade loop. Silently skips trades with malformed pnl, producing wrong module stats with no indication of why.

2. **`get_pnl_history()` settled-tickers loop** — `except Exception: pass`. Any exception here silently zeros out a position's P&L contribution. This is the main P&L loop — errors must be visible.

3. **`get_pnl_history()` exit-correction loop** — `except Exception: pass`. Corrections are applied here; a silent skip means the correction is never applied to the P&L total.

4. **`_build_state()` settled-tickers loop** — `except Exception: pass`. Same as #2 but for the `/api/state` endpoint path.

5. **`_build_state()` exit-corrections loop** — `except Exception: pass`. Same as #3 but for `/api/state`.

6. **`_build_state()` open-positions P&L loop** — `except Exception: pass`. Silently skips live price calculation for a position, leaving its P&L as None with no log.

**Spec for Group A:** Replace `except Exception: pass` with:
```python
except Exception as e:
    _logger.error("[dashboard:%s] %s", function_name, e, exc_info=True)
```
Do not re-raise — one bad record should not crash the endpoint. Continue the loop.

---

**Group B — MEDIUM SEVERITY (trade log parsing — errors here mean trades go missing)**

7. **`read_today_trades()`** — `except: pass` ← bare `except:`, change to `except Exception:`

8. **`read_all_trades()`** — `except: pass` ← bare `except:`, change to `except Exception:`

9. **`read_geo_log()`** — `except: pass` ← bare `except:`, change to `except Exception:`

10. **`read_crypto_15m_summary()`** — `except Exception: pass`

11. **`get_deposits()`** — `except: pass` ← bare `except:`, change to `except Exception:`

**Spec for Group B:** Replace bare `except:` with `except Exception as e:` and add:
```python
_logger.warning("[dashboard] JSON parse error in %s: %s", path_or_context, e)
```
One line per bad record — no `exc_info=True` (too noisy for parse errors). Include enough context to identify the file.

---

**Group C — LOW SEVERITY (optional cache reads, fallback paths — silently degrading is acceptable but should still log)**

12. **`get_mode()`** — `except Exception: pass`. Falls back to `'demo'`. Add:
    ```python
    _logger.warning("[dashboard] Could not read mode.json: %s", e)
    ```

13. **`get_account()` capital fetch** — `except Exception: STARTING_CAPITAL = 10000.0`. Not a silent pass, but no log. Add:
    ```python
    _logger.warning("[dashboard] get_capital() failed, using fallback $10000: %s", e)
    ```

14. **`get_active_positions()` live-mode Kalshi fallback** — `except Exception: pass  # Fall through`. The comment is good but there's no log. Add:
    ```python
    _logger.warning("[dashboard] Kalshi API failed for live positions, falling back to logs: %s", e)
    ```
    Do not use `exc_info=True` here — Kalshi client may throw SSL/timeout errors regularly; full tracebacks would be too noisy.

15. **`get_position_statuses()`** — `except Exception: pass` in the per-ticker loop. Optional enrichment. Add:
    ```python
    _logger.debug("[dashboard] Position status check failed for %s: %s", ticker, e)
    ```

16. **`/api/kalshi/weather` — weather cache parse loop** — `except: pass` ← bare `except:`, change to `except Exception:`. Add:
    ```python
    _logger.warning("[dashboard] Bad line in weather_scan.jsonl: %s", e)
    ```

17. **`/api/crypto/scan` — crypto prices cache** — `except Exception: pass`. Add:
    ```python
    _logger.warning("[dashboard] crypto_prices.json read failed: %s", e)
    ```

18. **`/api/crypto/scan` — smart money cache** — `except Exception: pass`. Add:
    ```python
    _logger.warning("[dashboard] crypto_smart_money.json read failed: %s", e)
    ```

19. **`/api/crypto/scan` — scan cache** — `except Exception: pass`. Add:
    ```python
    _logger.warning("[dashboard] crypto_scan_latest.json read failed: %s", e)
    ```

20. **`_build_state()` smart money cache** — `except Exception: pass`. Add:
    ```python
    _logger.warning("[dashboard] smart_money cache read failed: %s", e)
    ```

21. **`_cache_reload_loop()`** — no exception handling at all. See "Scope Addition" section above.

---

### Behavior Change
Errors that were previously invisible will now appear in the uvicorn/application logs. No change to response behavior — all fallbacks are preserved, just logged. The endpoint will not crash or change its response structure.

### What Could Go Wrong
- If the log volume is high (e.g., bad line in a large JSONL file parsed every 30s), warning logs could get noisy. Dev can demote high-frequency parse-error logs to DEBUG if needed after observing real log output.
- `exc_info=True` on Group A errors includes the full traceback — useful for debugging but verbose. Keep it on Group A (P&L loops) since those are where we most need stack traces.

---

## Summary Table

| Issue | Location | Change Type | Risk |
|-------|----------|-------------|------|
| 018 | `get_account()` return dict | Replace undefined names with existing helpers | None |
| 019 | `get_active_positions()` for-loop | Move `side` to first line of loop body; fix iteration bleed risk | None |
| 063 | `get_pnl_history()` chart points | Build from trade log daily buckets; return per-day values | Low — chart won't render until frontend builds `renderPnlChart` |
| 064 | `get_pnl_history()` `BOT_SRC` tuple | Add ws_* and crypto_15m sources; document deployed capital inconsistency with `_build_state()` as known gap | Low |
| 065 | `_build_state()` `exited` set | Include `action='settle'` in `exited` set only; keep `exit_records` dict as exit-only | Low |
| 066 | `get_pnl_history()` win rate counters | Dedup on trade_id vs. ticker; fallback to (ticker,side); skip on no match | Low — trade count will increase (expected) |
| 072 | Module-wide + `_cache_reload_loop()` | Add module-level logger; change bare `except:` to `except Exception:`; add exception handling to cache reload loop | Low — log volume only |
