# Batch 2 Data Scientist Specs
_Written by: Data Scientist_
_Date: 2026-04-04_
_Status: Ready for adversarial review before Dev implementation_

---

## Revision Log

| Rev | Date | Spec | Issue | Change |
|-----|------|------|-------|--------|
| R1 | 2026-04-04 | B2-DS-3 | BLOCKER — incorrect line range | Changed delete range from lines 63–66 to lines 63–68. The inner `try/except` block includes `except Exception:` (line 67) and `pass` (line 68); deleting only 63–66 left an orphaned `except` with no matching `try`, crashing `api.py` on import. Confirmed via direct inspection of `api.py`. |
| R2 | 2026-04-04 | B2-DS-1 | Minor — typo in function name | Fixed `pdt_today()` → `_pdt_today()` (missing leading underscore). One occurrence in the "The fix" section. |

---

## B2-DS-1: `settlement_checker.py` — Replace `date.today()` with PDT-aware date (lines 237–238)

### Context

`settlement_checker.py` (at `environments/demo/settlement_checker.py`) builds settle records for resolved positions. At lines 237–238, it uses `date.today()` to stamp both the fallback entry date and the settlement date onto each settle record:

- Line 237: `original_date = pos.get('date', date.today().isoformat())`  
- Line 238: `today_date = date.today().isoformat()`

The problem is `date.today()` returns the system clock date in UTC. The server runs UTC. The logger writes all trade files keyed by PDT date (via `_pdt_today()` in `logger.py`). Between midnight UTC and midnight PDT — a 7-hour window — `date.today()` returns tomorrow's date in PDT terms. Settlement checker then stamps settle records with the wrong date, and those records get written to the wrong day's trade file (or fail to find the right file at all).

### What the logger does

`logger.py` already defines:
```
def _pdt_today() -> date:
    return datetime.now(ZoneInfo('America/Los_Angeles')).date()
```
It is a module-level function. `settlement_checker.py` already imports `ZoneInfo` and defines its own `_PDT = ZoneInfo('America/Los_Angeles')` constant.

### What to check before implementing

`settlement_checker.py` already imports `_append_jsonl` from `agents.ruppert.data_scientist.logger`, but does **not** currently import `_pdt_today`. Dev should check whether importing `_pdt_today` from logger is clean (no circular import risk, no side-effect from importing it). 

If the import is clean: add `_pdt_today` to the existing logger import line in `settlement_checker.py`.

If there is any risk of a circular import or side effect: define a local one-liner helper in `settlement_checker.py` using the `_PDT` constant already defined there. The logic is identical: `datetime.now(_PDT).date()`.

### The fix

Replace both calls to `date.today()` at lines 237–238 with the PDT-aware equivalent (either imported or locally defined as above).

- Line 237: the fallback for `pos.get('date', ...)` should use `_pdt_today().isoformat()` so that if a position record is missing its original date, the fallback resolves to PDT date, not UTC.
- Line 238: `today_date` is used as the `date` field on the settle record — this must be PDT date so it matches the trade file naming convention.

### Why this matters

If this is not fixed, any settlement run between midnight UTC and 7 AM PDT stamps records with tomorrow's PDT date. The settle record either goes to the wrong file or creates a new file for a date that has no buy records. P&L for those positions will be orphaned until the next day catches up, and intraday P&L figures will be understated during that 7-hour window.

### Scope

Only lines 237–238 in `environments/demo/settlement_checker.py`. No other files.

---

## B2-DS-2: `position_tracker.py` — Replace `date.today()` with PDT-aware date (line 884)

### Context

`position_tracker.py` (at `agents/ruppert/trader/position_tracker.py`) contains the function `_settle_record_exists()` starting at line 881. This function checks whether a settle or exit record already exists for a given (ticker, side) pair before allowing a new one to be written (idempotency guard).

At line 884 it does:
```
check_date = date.today() - timedelta(days=day_offset)
```

It checks today and yesterday (day_offset = 0 and 1) for an existing record. The trade file it reads is named `trades_{check_date}.jsonl`. If `date.today()` returns UTC date, the file name won't match — trade files are named by PDT date via the logger. Same class of bug as B2-DS-1.

### What `position_tracker.py` already has

The file already defines `_today_pdt()` as a module-level helper (around line 52):
```
def _today_pdt() -> str:
    return datetime.now(pytz.timezone('America/Los_Angeles')).strftime('%Y-%m-%d')
```

Note: this helper returns a **string** (YYYY-MM-DD), not a `date` object.

The fix at line 884 needs a `date` object (because it does arithmetic with `timedelta`). Dev has two options:

1. Use `date.fromisoformat(_today_pdt())` to get the date object from the existing helper.
2. Add a new helper that returns a `date` object (consistent with logger's `_pdt_today()`), and use that.

Either option is acceptable. The existing `_today_pdt()` string helper is used elsewhere in the file — do not change its return type.

### The fix

At line 884, replace `date.today()` with a PDT-aware date value — either by calling `date.fromisoformat(_today_pdt())` or by using a new `date`-returning PDT helper.

The subtracted `timedelta(days=day_offset)` arithmetic stays the same. Only the base date changes.

### Why this matters

`_settle_record_exists()` is the idempotency guard. If it looks for settlement records in the wrong file (wrong UTC-keyed name), it finds nothing, incorrectly concludes no settle record exists, and may allow a duplicate settle record to be written. This is the midnight UTC–PDT window problem: for 7 hours each day, the guard is blind to today's existing records because it's searching for a file that doesn't exist (tomorrow's file by PDT convention).

### Scope

Only line 884 in `agents/ruppert/trader/position_tracker.py`. No other files.

---

## B2-DS-3: `dashboard/api.py` — Fix `push_alert` NameError in `_cache_reload_loop()` (line 64)

### Context

In `environments/demo/dashboard/api.py`, the function `_cache_reload_loop()` is a background daemon thread that reloads the price cache every 60 seconds. When the reload fails, it catches the exception, logs it via `_logger.error()`, and then attempts to call:

```python
push_alert("price_cache_failure", f"market_cache.load() failed: {e}", level="warning")
```

`push_alert` is never imported anywhere in `api.py`. This raises a `NameError` at runtime. The outer `try/except Exception: pass` swallows the error silently — so the alert is never sent, no exception surfaces, and there is no indication in logs that the alert call failed. The only evidence that anything broke is the `_logger.error()` that fires before it.

### Where `push_alert` is defined

A search of the codebase found `push_alert` defined in multiple places:

- `agents/ruppert/trader/utils.py` — a shared utility version that logs to an alert candidate event file
- `agents/ruppert/trader/post_trade_monitor.py` — a local copy
- `environments/demo/ruppert_cycle.py` — another local copy

The version in `agents/ruppert/trader/utils.py` is the most appropriate source for a dashboard import. It is a shared utility, not tied to a specific component.

### My recommendation: Option B — Remove the call, rely on `_logger.error()`

**Do not add the import.** Here is why:

1. `api.py` is the dashboard — its ROLE.md description is read-only views of truth files. Sending alerts from the dashboard is not its job. Alerts are the Data Scientist's responsibility.

2. The `_logger.error()` call on the line before already logs the failure with full exception info (`exc_info=True`). That's visible in the process logs. There is no silent gap on the logging side.

3. Importing `push_alert` from `utils.py` introduces a dependency between the dashboard and the trader module. That coupling is undesirable and would make `api.py` harder to reason about.

4. The `push_alert` in `utils.py` logs to an event file. The dashboard process may not have the correct path context to write to that file reliably, and any failure there would also be silently swallowed.

5. The outer `except: pass` is appropriate for keeping the loop alive — that part is correct. The problem is only the dead alert call inside it.

### The fix

Remove lines 63–68 (the inner `try: push_alert(...) / except Exception: pass` block) entirely. Leave the `_logger.error()` call at line 62 in place — that is sufficient. The daemon loop continues as before; failures are now visible in process logs without any dead code.

The result is:

```
except Exception as e:
    _logger.error("[dashboard] _cache_reload_loop: market_cache.load() failed — "
                  "price cache is stale: %s", e, exc_info=True)
    # Do NOT re-raise — keep the loop alive so it retries next cycle
```

No new imports. No new dependencies. Clean and correct.

### Scope

Only `environments/demo/dashboard/api.py`, lines 63–68 (the inner try/except push_alert block). The surrounding function structure stays the same.

---

_End of Batch 2 DS specs. Three issues covered: B2-DS-1, B2-DS-2, B2-DS-3._
