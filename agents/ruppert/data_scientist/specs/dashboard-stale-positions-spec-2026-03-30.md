# Bug Fix Spec: Stale 15m Positions in Open Positions List

**Date:** 2026-03-30  
**Author:** Data Scientist (Ruppert)  
**File:** `environments/demo/dashboard/api.py`  
**Function:** `is_settled_ticker()` (~line 253)  
**Severity:** Medium — expired 15m positions accumulate in the open positions list indefinitely

---

## Problem

`is_settled_ticker()` uses a regex to parse date-encoded tickers and determine if they have already settled. The current regex is:

```python
r'^(\d{2})([A-Z]{3})(\d{2})(\d{2})?$'
```

This matches two formats:
- `26MAR30` — 2-digit year + 3-letter month + 2-digit day (date only)
- `26MAR3011` — same, with optional 2-digit hour appended

**15m crypto tickers use a 4-digit time suffix**, e.g. `26MAR301300` (day `30` + time `1300`).  
The regex expects `(\d{2})?` (0 or 2 digits) after the day, so `1300` (4 digits) fails to match.  
Result: `is_settled_ticker()` returns `False` for all expired 15m positions → they stay open forever.

---

## Confirmed Root Cause

Verified in source (lines 253–287):

```python
m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2})?$', part)
if m:
    ...
    if mkt_date == today and m.group(4):
        hour = int(m.group(4))
        ...
        if now_edt >= settle_edt:
            return True
```

The group(4) logic already handles the "same-day + hour" check. The only failure is the regex not matching the 4-digit time suffix in the first place.

---

## Fix

### BEFORE

```python
m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2})?$', part)
```

### AFTER

```python
m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2}\d{2}?)?$', part)
```

Wait — cleaner to express this explicitly:

```python
m = _re.match(r'^(\d{2})([A-Z]{3})(\d{2})(\d{2}|\d{4})?$', part)
```

This matches:
| Ticker | Matches? | Notes |
|---|---|---|
| `26MAR30` | ✅ | Date only (weather) |
| `26MAR3011` | ✅ | Date + 2-digit hour (weather/hourly) |
| `26MAR301300` | ✅ | Date + 4-digit time (15m crypto) — **was broken** |
| `26MAR30130` | ❌ | 3-digit suffix — intentionally rejected |

---

## Settlement Logic for 4-digit time

When group(4) is 4 digits (e.g. `1300`), the current hour-check logic (`int(m.group(4))`) will parse it as `1300` (an invalid hour). The same-day settlement logic must be updated to handle both cases:

```python
if mkt_date == today and m.group(4):
    time_str = m.group(4)
    if len(time_str) == 2:
        hour = int(time_str)
        settle_edt = _dt(mkt_date.year, mkt_date.month, mkt_date.day, hour)
    else:  # 4-digit HHMM
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        settle_edt = _dt(mkt_date.year, mkt_date.month, mkt_date.day, hour, minute)
    if now_edt >= settle_edt:
        return True
```

---

## Summary of Changes

1. **Regex** (line ~261): `(\d{2})?` → `(\d{2}|\d{4})?`
2. **Same-day settlement logic** (line ~276): parse group(4) as `HHMM` when 4 digits, otherwise `HH`

No other changes needed. Existing tests for `26MAR30` and `26MAR3011` formats are unaffected.
