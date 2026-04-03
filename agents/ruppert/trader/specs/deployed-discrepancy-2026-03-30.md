# Spec: Capital Deployed Discrepancy — Notification vs Dashboard
**Date:** 2026-03-30
**Author:** Trader (formal BEFORE/AFTER spec; supplements DS root-cause doc)
**Status:** BUG — `get_daily_exposure()` counts expired crypto_15m positions; dashboard excludes them via `is_settled_ticker()`

---

## Summary

The notification's "Capital Deployed" figure and the dashboard's "Capital Deployed" figure
diverge by the cost of crypto_15m positions that have passed their settlement time but have
not yet received an explicit `settle` record from `check_settlements()`.

**Observed gap on 2026-03-30 at 3pm:**
- Notification: **$2,294.85**
- Dashboard: **$1,865.13**
- Gap: **$429.72** = expired-but-unsettled crypto_15m positions

---

## Code Locations

### `logger.get_daily_exposure()` — `agents/ruppert/data_scientist/logger.py` (~line 179)

```python
def get_daily_exposure(module: str = None) -> float:
    START_DATE = '2026-03-26'

    entries   = {}   # key: (ticker, side) → accumulated size_dollars
    exit_keys = set()

    for fname in sorted(os.listdir(TRADES_DIR)):
        ...
        for line in f:
            entry = json.loads(line)
            ticker = entry.get('ticker', '')
            side   = entry.get('side', '')
            action = entry.get('action', 'buy')
            key    = (ticker, side)
            if action in ('exit', 'settle'):
                exit_keys.add(key)
                entries.pop(key, None)
            else:
                if module is not None:
                    entry_module = entry.get('module', '')
                    if not (entry_module == module or
                            entry_module.startswith(module + '_')):
                        continue
                entries[key] = entries.get(key, 0) + entry.get('size_dollars', 0)

    return sum(size for key, size in entries.items() if key not in exit_keys)
```

A position is removed from the sum **only when an explicit `action='exit'` or
`action='settle'` record appears in the trade log.** Until then, any buy — including
an expired crypto_15m position — is counted as deployed.

---

### `is_settled_ticker()` — `environments/demo/dashboard/api.py` (~line 253)

```python
def is_settled_ticker(ticker: str) -> bool:
    """Return True if ticker contains a past date (market already settled)."""
    parts = ticker.upper().split('-')
    for part in parts:
        m = re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2}|\d{4})?$', part)
        if m:
            yy, mon, dd = m.group(1), m.group(2), m.group(3)
            mkt_date = date(2000 + int(yy), month_num, int(dd))
            if mkt_date < today:
                return True
            if mkt_date == today and m.group(4):
                # Compare settlement time (HHMM) vs current EDT time
                ...
                if now_edt >= settle_edt:
                    return True
    return False
```

For a ticker like `KXBTC15M-26MAR301445-45`, this returns `True` as soon as 14:45 EDT
passes, regardless of whether a `settle` record has been written.

The dashboard's open position list filters out any ticker where `is_settled_ticker()`
returns True:
```python
# In api.py _build_state():
if is_settled_ticker(ticker):
    continue
```

---

## BEFORE (Current Behavior)

```
notification path (capital.py → logger.get_daily_exposure()):
  position = (KXBTC15M-26MAR301445-45, 'yes', $50)
  → buy record exists, no settle record yet
  → counted as deployed = $50 ✓ (from notification's perspective)

dashboard path (api.py _build_state() → is_settled_ticker()):
  ticker = 'KXBTC15M-26MAR301445-45'
  → 14:45 EDT has passed → is_settled_ticker() returns True
  → position EXCLUDED from deployed = $0

result:
  notification deployed:  $2,294.85  (includes expired-unsettled 15m positions)
  dashboard deployed:     $1,865.13  (excludes expired-unsettled 15m positions)
  gap:                    $429.72
```

**Secondary risk:** the daily cap check in `run_weather_scan()` and `run_crypto_scan()`
uses `get_daily_exposure()` as `deployed_today`. If that figure is inflated by
expired-unsettled 15m positions, the global cap check may prematurely block new entries
in other modules. (Minor concern — 15m positions settle frequently — but real during the
gap window.)

---

## AFTER (Proposed Fix)

**Option A — preferred:** In `logger.get_daily_exposure()`, skip tickers where
`is_settled_ticker(ticker)` returns True. This aligns the notification with the
dashboard without touching any display code.

### Implementation

The `is_settled_ticker()` function is currently in `environments/demo/dashboard/api.py`.
To avoid a circular import (`logger.py` importing from `dashboard/api.py`), extract
the function to a shared utility module first:

**Step 1:** Create `agents/ruppert/data_scientist/ticker_utils.py` (new file):

```python
"""ticker_utils.py — Shared ticker classification utilities.

Extracted from environments/demo/dashboard/api.py to avoid circular imports.
"""
import re
from datetime import date, datetime, timedelta


def is_settled_ticker(ticker: str) -> bool:
    """Return True if ticker contains a past date/time (market already settled).

    Handles both date-only (26MAR11) and date+time (26MAR1117 or 26MAR111300) formats.
    Uses EDT (UTC-4) for intraday comparison, matching the existing dashboard logic.
    """
    months = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
    }
    today = date.today()
    parts = ticker.upper().split('-')
    for part in parts:
        m = re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2}|\d{4})?$', part)
        if m:
            yy, mon, dd = m.group(1), m.group(2), m.group(3)
            month_num = months.get(mon)
            if not month_num:
                continue
            try:
                mkt_date = date(2000 + int(yy), month_num, int(dd))
                if mkt_date < today:
                    return True
                if mkt_date == today and m.group(4):
                    time_str = m.group(4)
                    now_edt = datetime.utcnow() - timedelta(hours=4)
                    if len(time_str) == 2:
                        settle_edt = datetime(mkt_date.year, mkt_date.month, mkt_date.day,
                                              int(time_str))
                    else:
                        settle_edt = datetime(mkt_date.year, mkt_date.month, mkt_date.day,
                                              int(time_str[:2]), int(time_str[2:]))
                    if now_edt >= settle_edt:
                        return True
            except Exception:
                pass
    return False
```

**Step 2:** In `logger.py`, update `get_daily_exposure()` to skip expired tickers:

```python
# BEFORE (in the else branch of get_daily_exposure):
else:
    if module is not None:
        entry_module = entry.get('module', '')
        if not (entry_module == module or
                entry_module.startswith(module + '_')):
            continue
    entries[key] = entries.get(key, 0) + entry.get('size_dollars', 0)

# AFTER:
else:
    if module is not None:
        entry_module = entry.get('module', '')
        if not (entry_module == module or
                entry_module.startswith(module + '_')):
            continue
    # Skip tickers whose settlement time has already passed (aligns with dashboard)
    try:
        from agents.ruppert.data_scientist.ticker_utils import is_settled_ticker as _is_settled
        if _is_settled(ticker):
            continue
    except Exception:
        pass  # on import failure, include position (conservative)
    entries[key] = entries.get(key, 0) + entry.get('size_dollars', 0)
```

**Step 3:** Update `dashboard/api.py` to import `is_settled_ticker` from the shared
utility instead of defining it inline:

```python
# BEFORE (in api.py):
def is_settled_ticker(ticker: str) -> bool:
    ...  # full implementation

# AFTER:
from agents.ruppert.data_scientist.ticker_utils import is_settled_ticker  # noqa: F401
```

This makes `is_settled_ticker` a single canonical implementation with no drift risk.

---

## Acceptance Criteria

1. After fix: `logger.get_daily_exposure()` and dashboard's deployed figure agree
   within $0.01 rounding for any state where no positions are in the
   "expired but not yet settled" gap window.
2. A crypto_15m position whose ticker's settlement time has passed is **not** counted
   in `get_daily_exposure()` — even if no `settle` record has been written yet.
3. Non-15m positions (weather, crypto daily, fed, geo) are **not** affected:
   `is_settled_ticker()` returns False for all tickers without date/time embeds.
4. The global daily cap check (used in `run_weather_scan()`, `run_crypto_scan()`, etc.)
   reflects the same deployed figure as the dashboard — no premature cap blocking from
   expired-unsettled 15m positions.
5. `get_daily_exposure(module='crypto_15m')` also filters expired tickers correctly.
6. `is_settled_ticker()` in `dashboard/api.py` is replaced by an import from
   `ticker_utils.py` — no duplicate implementations.
7. Exception in `is_settled_ticker()` import/call causes the position to be **included**
   (conservative: never under-count deployed capital on error).

---

## Files to Change

| File | Change |
|------|--------|
| `agents/ruppert/data_scientist/ticker_utils.py` | **NEW FILE** — extract `is_settled_ticker()` here |
| `agents/ruppert/data_scientist/logger.py` | `get_daily_exposure()` — add `is_settled_ticker` filter in the `else` branch |
| `environments/demo/dashboard/api.py` | Replace inline `is_settled_ticker()` definition with import from `ticker_utils` |

---

## Related Specs

- DS root-cause analysis: `agents/ruppert/trader/specs/deployed-discrepancy-2026-03-30.md`
  (this file — DS spec was pre-existing; this is the formal Trader BEFORE/AFTER for Dev)
- `daily-cap-reset-bug-2026-03-30.md` — separate bug: per-module cap reset to 0 per scan
- `crypto-15m-cap-redesign-trader-review-2026-03-30.md` — crypto_15m cap architecture
