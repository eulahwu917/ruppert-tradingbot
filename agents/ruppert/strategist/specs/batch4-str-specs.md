# Batch 4 Strategist Specs
_Authored: 2026-04-04 | Strategist → adversarial review → Dev pipeline_
_Status: Revised after adversarial review — Ready for Dev_

---

## Revision Log

| Rev | Date       | Author     | Summary |
|-----|------------|------------|---------|
| 1.0 | 2026-04-04 | Strategist | Initial spec — adversarial review flagged 3 issues |
| 1.1 | 2026-04-04 | Strategist | **Issue 1:** NFP/CPI/FOMC dates verified against BLS and Federal Reserve official sources — multiple corrections applied (see calendar section). **Issue 2:** Deployment order requirement added — `utils.py` must be deployed first; conditional import with loud warning added as safety net. **Issue 3:** Acceptance criterion AC-9 added — `has_macro_event_within()` must raise or log a loud warning at startup if the calendar for the current year is empty. |

---

## B4-STR-1: R9 Macro Event Filter — Remove Dead Code, Implement Properly for LIVE

### Background

R9 is supposed to block `crypto_15m` entries during major macro events (FOMC, CPI, NFP, tariffs) — 2 hours before and 1 hour after. The System Map documents R9 as an active risk filter.

It has never fired. The implementation in `crypto_15m.py` (lines ~767–773) tries to import `has_macro_event_within` from `ruppert_cycle`. That function does not exist anywhere in the codebase. The `ImportError` is silently caught and execution falls through. R9 is dead code.

---

### The Decision

**Option A:** Remove R9 entirely for DEMO. Document it as a known gap. Add it to the pre-LIVE checklist.

**Option B:** Implement R9 properly right now using a static FOMC/CPI/NFP calendar — no external API needed.

---

### My Recommendation: Option B for LIVE, delivered now

Here's the reasoning:

**For DEMO:** Option A is fine. We've been running without R9 this whole time and the bot is profitable. Dead code removal + honest documentation is net positive with zero risk. However, we're already speccing a Batch 4 fix. If Option B is straightforward to implement (and it is — static calendar, no API dependency), doing it now costs one sprint and closes the gap permanently.

**For LIVE:** R9 is not optional. Kalshi crypto 15m markets are extremely sensitive to macro surprises. FOMC day volatility routinely distorts settlement prices. CPI and NFP create momentum shocks that can flip a position in the final 2 minutes before settlement. We cannot go live with this protection documented but absent. It's on the pre-LIVE checklist already — the only question is whether we do it now or in a separate sprint later.

**Why Option B now:** The static calendar approach is clean, deterministic, and safe — no API dependency, no runtime failure modes. The calendar needs maintenance (someone updates it quarterly), but that's a known, low-effort operational cost. The alternative — doing Option A now and Option B "before LIVE" — just creates a gap we have to track and a sprint we have to schedule later. Do it once, do it right.

**Recommendation: Implement Option B.**

---

### Spec

#### 1. New function: `has_macro_event_within()`

**Where it lives:** `agents/ruppert/trader/utils.py`

This is the correct home. It's not a strategy decision (not `strategy.py`), not a data science function (not `capital.py`), and not specific to the cycle orchestrator (not `ruppert_cycle.py`). It's a utility check used by the Trader. `utils.py` already exists in the trader directory and is the right place for shared helpers.

**Signature:**
```python
def has_macro_event_within(minutes_before: int = 120, minutes_after: int = 60) -> bool:
```

Returns `True` if the current UTC time falls within `minutes_before` of any scheduled macro event OR within `minutes_after` of any scheduled macro event. Returns `False` otherwise.

**Parameters:**
- `minutes_before`: how far ahead to look (default 120 = 2 hours). This is the "pre-event blackout" window.
- `minutes_after`: how long post-event to block (default 60 = 1 hour). This is the "post-event settling" window.

Note: The current dead code calls `has_macro_event_within(minutes=30)`. That's different from the original design intent (2h pre / 1h post). The `minutes=30` was likely a placeholder. **Use the original design: 120 min before, 60 min after.** See the R9 description in the overnight audit. The call site in `crypto_15m.py` will need to be updated to the new signature.

---

#### 2. The calendar

The function checks against a hardcoded list of known event datetimes. All times are in UTC.

The calendar should contain all **2026** scheduled dates for:
- **FOMC rate decisions** — 8 meetings per year, decision released at 14:00 ET (19:00 UTC). Also include the minutes release dates (3 weeks after each meeting, 14:00 ET).
- **CPI releases** — monthly, released at 08:30 ET (13:30 UTC). Use the BLS published 2026 schedule.
- **NFP (Non-Farm Payrolls)** — released at 08:30 ET (13:30 UTC). Note: BLS does not always release on the first Friday — use the official BLS published dates, which can shift for holidays and scheduling reasons.

Tariff announcements and unscheduled events: these cannot be statically scheduled. R9 handles scheduled events only. Unscheduled events are caught by R1 (volatility gate) — that's the right defense for surprise events. R9 and R1 are complementary, not redundant.

**Format:** A Python list of `datetime` objects (UTC-aware, using `timezone.utc`). One entry per event.

**The actual dates to populate (2026 calendar — verified against official sources):**

> ⚠️ **VERIFICATION STATUS:** NFP and CPI dates below are verified against the official BLS published 2026 schedule (https://www.bls.gov/schedule/news_release/empsit.htm and https://www.bls.gov/schedule/news_release/cpi.htm). FOMC decision dates are verified against the Federal Reserve published calendar (https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm). FOMC minutes release dates beyond February 18 are calculated as 3 weeks post-decision and flagged for verification below.

**FOMC Decision Dates (2026, 19:00 UTC = 14:00 ET):**
- Jan 28, Mar 18, Apr 29, Jun 17, Jul 29, Sep 16, Oct 28, Dec 9

  _Source: Federal Reserve official calendar. Corrections from v1.0: Jan 29→Jan 28; May 6 removed (no May meeting), replaced with Apr 29; Nov 4 removed (no November meeting), replaced with Oct 28; Dec 16→Dec 9._

**FOMC Minutes Release Dates (2026, 19:00 UTC = 14:00 ET):**
- Feb 18 _(verified — confirmed in Fed calendar)_
- Apr 8 _(approx. 3 weeks after Mar 18 — flag for verification before deploy)_
- May 20 _(approx. 3 weeks after Apr 29 — flag for verification before deploy; v1.0 incorrectly listed May 27 based on wrong decision date)_
- Jul 8 _(approx. 3 weeks after Jun 17 — flag for verification before deploy)_
- Aug 19 _(approx. 3 weeks after Jul 29 — flag for verification before deploy)_
- Oct 7 _(approx. 3 weeks after Sep 16 — flag for verification before deploy)_
- Nov 18 _(approx. 3 weeks after Oct 28 — flag for verification before deploy; v1.0 incorrectly listed Nov 25 based on wrong decision date)_
- Dec 30 _(approx. 3 weeks after Dec 9 — flag for verification before deploy; v1.0 incorrectly listed Jan 7 2027 based on wrong decision date)_

**CPI Release Dates (2026, 13:30 UTC = 08:30 ET) — verified against BLS official schedule:**
- Jan 13, Feb 13, Mar 11, Apr 10, May 12, Jun 10, Jul 14, Aug 12, Sep 11, Oct 14, Nov 10, Dec 10

  _Source: https://www.bls.gov/schedule/news_release/cpi.htm. Corrections from v1.0: Jan 14→Jan 13; Feb 11→Feb 13; May 13→May 12; Sep 10→Sep 11; Oct 13→Oct 14; Nov 12→Nov 10._

**NFP Release Dates (2026, 13:30 UTC = 08:30 ET) — verified against BLS official schedule:**
- Jan 9, Feb 11, Mar 6, Apr 3, May 8, Jun 5, Jul 2, Aug 7, Sep 4, Oct 2, Nov 6, Dec 4

  _Source: https://www.bls.gov/schedule/news_release/empsit.htm. Note: BLS publishes official dates that may differ from "first Friday" due to holiday adjustments. May 8 is the official BLS date for April data (not May 1). Jul 2 is the official BLS date for June data (moved to Thursday due to July 4 holiday proximity). Corrections from v1.0: Feb 6→Feb 11; Jul 10→Jul 2._

---

#### 3. Logic inside the function

```python
def has_macro_event_within(minutes_before: int = 120, minutes_after: int = 60) -> bool:
    import logging
    from datetime import datetime, timezone, timedelta

    logger = logging.getLogger(__name__)
    now = datetime.now(timezone.utc)

    current_year = now.year
    year_events = [e for e in MACRO_CALENDAR if e.year == current_year]

    # AC-9: Loud warning if calendar for current year is empty
    if not year_events:
        logger.error(
            "[R9] MACRO_CALENDAR has NO events for year %d — R9 filter is INACTIVE. "
            "Update the calendar in utils.py before running live.",
            current_year
        )
        # Fail safe: treat as no block (conservative for profitability).
        # Dev note: if stricter safety is preferred, raise RuntimeError here instead.
        return False

    for event_time in year_events:
        window_start = event_time - timedelta(minutes=minutes_before)
        window_end = event_time + timedelta(minutes=minutes_after)
        if window_start <= now <= window_end:
            return True
    return False
```

Simple. No fuzzy logic, no external calls, no caching needed. The calendar is small enough that iterating all entries is fast.

---

#### 4. Startup validation (empty calendar guard)

At module load time (not just at call time), `utils.py` should log a startup warning if the current year has no calendar entries. This catches misconfiguration early — before the first evaluation — rather than silently deactivating R9:

```python
# At module level in utils.py, after MACRO_CALENDAR is defined:
import logging as _logging
import datetime as _datetime

_startup_year = _datetime.datetime.now(_datetime.timezone.utc).year
_year_event_count = sum(1 for e in MACRO_CALENDAR if e.year == _startup_year)
if _year_event_count == 0:
    _logging.getLogger(__name__).error(
        "[R9] STARTUP WARNING: MACRO_CALENDAR contains 0 events for %d. "
        "R9 macro filter will be INACTIVE. Update the calendar.",
        _startup_year
    )
```

This fires once when `utils.py` is first imported, making the misconfiguration visible in logs immediately.

---

#### 5. Logging

When R9 fires (returns True), `crypto_15m.py` should log at INFO level:
```
[crypto_15m] R9 block: macro event window active — MACRO_EVENT_RISK
```

This matches the existing block logging pattern. The return dict `{'block': 'MACRO_EVENT_RISK', ...}` is already correct in the dead code — keep that.

---

#### 6. Changes to `crypto_15m.py`

The existing dead code block at lines ~767–773:
```python
# R9: Macro event (reuse from main cycle if available)
try:
    from ruppert_cycle import has_macro_event_within
    if has_macro_event_within(minutes=30):
        return {'block': 'MACRO_EVENT_RISK', 'okx_volume_pct': okx_volume_pct}
except (ImportError, AttributeError):
    pass  # Not available in all contexts
```

**Replace entirely with:**
```python
# R9: Macro event filter
# DEPLOYMENT REQUIREMENT: utils.py must be deployed and importable before this
# change goes live. See deployment order note in B4-STR-1 spec.
try:
    from agents.ruppert.trader.utils import has_macro_event_within
except ImportError:
    import logging as _log
    _log.getLogger(__name__).error(
        "[crypto_15m] CRITICAL: Cannot import has_macro_event_within from utils.py. "
        "R9 macro filter is INACTIVE. Deploy utils.py before this module."
    )
    has_macro_event_within = None

if has_macro_event_within is not None and has_macro_event_within(minutes_before=120, minutes_after=60):
    logger.info('[crypto_15m] R9 block: macro event window active')
    return {'block': 'MACRO_EVENT_RISK', 'okx_volume_pct': okx_volume_pct}
```

**Why the conditional import (not a bare import):**

The ideal deployment is a single atomic commit that ships `utils.py` changes and `crypto_15m.py` changes together. In that case, the `ImportError` branch never fires. However, if for any reason `crypto_15m.py` is deployed before `utils.py` is importable (partial rollout, failed deploy of utils, misconfigured path), the bare import would crash every evaluation. The conditional import prevents that crash while logging a loud, hard-to-miss ERROR that makes the problem immediately visible. This is **not a silent failure** — it's a loud warning with graceful degradation.

**Preferred deployment approach:** Ship both files in the same commit. The conditional import is a safety net, not an invitation to deploy out of order.

---

#### 7. Deployment Order (Required)

> ⚠️ **DEPLOYMENT REQUIREMENT — READ BEFORE IMPLEMENTING**
>
> `agents/ruppert/trader/utils.py` (with `has_macro_event_within` and `MACRO_CALENDAR`) **must be deployed and importable** before `crypto_15m.py` changes go live.
>
> **Preferred:** Deploy both files in the same commit/PR. This is the clean path.
>
> **If staged rollout is required:** Deploy and verify `utils.py` first. Confirm `has_macro_event_within` is importable from the deployment environment. Then deploy `crypto_15m.py`.
>
> The conditional import in `crypto_15m.py` (section 6 above) is a safety net for unexpected partial deploys — it will log a CRITICAL-level error and degrade gracefully (R9 inactive) rather than crashing. But this safety net should never be relied upon in normal operations.

---

#### 8. System Map update

After Dev implements and QA passes, the System Map entry for R9 must be updated:
- Remove the "STUB/DEAD CODE" annotation
- Update the description to: "Macro event filter — blocks entries 2h before / 1h after FOMC, CPI, NFP. Static 2026 calendar in `agents/ruppert/trader/utils.py`. Tariff/unscheduled events handled by R1 (vol gate)."

---

#### 9. Pre-LIVE checklist update

The pre-LIVE checklist currently has R9 as an open item. After this fix ships:
- Change to: "R9 macro filter: ✅ Implemented. Action needed before LIVE: update calendar with 2027 event dates. Verify FOMC minutes dates (currently calculated as T+21d — confirm against Fed releases page)."

---

### What This Does NOT Do

- Does not handle tariff announcements or surprise Fed statements. Those are unscheduled and belong to R1 (volatility gate).
- Does not use an external API. No network dependency in this filter.
- Does not affect any other module. Only `crypto_15m.py` calls this filter.
- Does not change the `minutes_before`/`minutes_after` defaults from config. These are hardcoded at the call site for now — if the Optimizer later wants to tune them, they can be moved to config. Don't pre-optimize.

---

### Acceptance Criteria

1. `has_macro_event_within(minutes_before=120, minutes_after=60)` exists in `agents/ruppert/trader/utils.py` and is importable.
2. The function returns `True` when called within 2 hours before or 1 hour after any event in the calendar.
3. The function returns `False` at all other times.
4. The old dead code block in `crypto_15m.py` is replaced with the new conditional import block (section 6). The import failure path logs at ERROR level with a clear message — not a silent pass.
5. A test or manual verification confirms: pick a known event datetime, mock `datetime.now(utc)` to T-60min, assert returns True. Mock to T+90min (within 1h after), assert True. Mock to T-150min (2.5h before), assert False.
6. System Map R9 entry updated — "STUB/DEAD CODE" annotation removed.
7. Pre-LIVE checklist updated — R9 item marked implemented, calendar maintenance noted.
8. No change to R1, R2, R3, R4, R5, R6, R7, R8, R10 — only R9 is affected.
9. **(NEW — AC-9)** `has_macro_event_within()` logs an ERROR-level warning at startup (module load) AND at call time if the `MACRO_CALENDAR` contains zero events for the current year. The warning must be clearly visible in logs (ERROR or above — not DEBUG or INFO). A test confirms: with an empty or wrong-year calendar, calling `has_macro_event_within()` produces a log message at ERROR level containing "INACTIVE" or equivalent. It must NOT silently return `False` without any trace in logs.

---

### Risk to DEMO

Low. R9 was never firing before. Activating it means some entries near FOMC/CPI/NFP windows will be blocked. That's the intended behavior. The 2h/1h window is conservative — if anything, it's slightly over-protective, which is fine for a risk filter.

The only risk: if a major macro event falls on a day when the bot would have had strong signals, those entries get blocked and we miss profit. That's acceptable — the filter exists to prevent losses from macro volatility, not to guarantee maximum P&L.

---

_Spec status: Revised v1.1 — Ready for Dev_
_Author: Strategist_
_Revision date: 2026-04-04_
