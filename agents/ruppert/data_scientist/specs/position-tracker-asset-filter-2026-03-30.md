# Spec: Add `get_active_positions()` with `asset=` and `settlement_date=` kwargs

**Date:** 2026-03-30  
**Author:** Data Scientist  
**File:** `agents/ruppert/trader/position_tracker.py`  
**Status:** Ready for Dev

---

## Background

`crypto_1d.py` already calls `position_tracker.get_active_positions(asset=..., settlement_date=...)` at line 667, but the function **does not exist** in `position_tracker.py`. The call is wrapped in a `try/except (ImportError, TypeError)` that silently falls back to a trade-log scan when the function is missing. This means the fast in-memory path is never used.

The current public API of `position_tracker.py` consists of:
- `add_position()`
- `remove_position()`
- `get_tracked()` — returns a dict copy of `_tracked`, keyed as `'ticker::side'` strings
- `is_tracked(ticker, side)`

There is no `get_active_positions()` function. This spec adds it.

---

## BEFORE

`position_tracker.py` has no `get_active_positions()` function.

```python
# position_tracker.py — current public API (no get_active_positions)

def get_tracked() -> dict:
    """Return copy of tracked positions (for diagnostics). Keys serialized as 'ticker::side'."""
    return {f'{k[0]}::{k[1]}': v for k, v in _tracked.items()}


def is_tracked(ticker: str, side: str) -> bool:
    return (ticker, side) in _tracked
```

Call site in `crypto_1d.py` (line 667) always falls through to the slow trade-log fallback:

```python
try:
    from agents.ruppert.trader.position_tracker import get_active_positions
    active = get_active_positions(asset=asset, settlement_date=settlement_date)
    ...
except (ImportError, TypeError):
    # position_tracker doesn't support filtered get_active_positions - fall back to trade log
    pass
```

---

## AFTER

Add `get_active_positions()` immediately after `get_tracked()` in `position_tracker.py`:

```python
def get_active_positions(
    asset: str = None,
    settlement_date: str = None,
) -> list[dict]:
    """Return active tracked positions, optionally filtered by asset and/or settlement date.

    Args:
        asset:           If provided (e.g. 'BTC'), only return positions whose ticker
                         contains this string (case-insensitive).
        settlement_date: If provided (e.g. '2026-03-31'), only return positions whose
                         ticker encodes this settlement date. The date is parsed from
                         tickers in the format {EVENT}-{YY}{MON}{DD}-{STRIKE}
                         (e.g. 'KXBTC2026-26MAR31-B90000').

    Returns:
        List of position dicts. Each dict contains at minimum:
            ticker, side, quantity, entry_price, module, title, exit_thresholds
        A 'market_id' key is also set to the ticker value for compatibility
        with callers that use pos.get('market_id').

    Filtering behaviour:
        - asset=None, settlement_date=None  →  return all active positions (no filter)
        - asset='BTC'                       →  ticker must contain 'BTC' (case-insensitive)
        - settlement_date='2026-03-31'      →  ticker must encode settlement on 2026-03-31
        - Both provided                     →  both conditions must match (AND logic)

    No existing callers break: all kwargs default to None, so bare
    get_active_positions() returns all positions as expected.
    """
    MONTH_MAP = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
    }

    # Parse target settlement date once (avoid re-parsing per position)
    target_date = None
    if settlement_date is not None:
        try:
            from datetime import date as _date
            target_date = _date.fromisoformat(settlement_date)
        except ValueError:
            pass  # invalid date string — filter will match nothing

    results = []
    for (ticker, side), data in _tracked.items():
        # --- asset filter ---
        if asset is not None:
            if asset.upper() not in ticker.upper():
                continue

        # --- settlement_date filter ---
        if settlement_date is not None:
            # Parse date from ticker: look for -{YY}{MON}{DD}- pattern
            import re as _re
            m = _re.search(r'-(\d{2})([A-Z]{3})(\d{2})-', ticker.upper())
            if not m:
                continue  # no date in ticker; skip when filter is active
            try:
                yy  = int(m.group(1))
                mon = MONTH_MAP.get(m.group(2))
                dd  = int(m.group(3))
                if mon is None:
                    continue
                from datetime import date as _date
                ticker_date = _date(2000 + yy, mon, dd)
            except (ValueError, KeyError):
                continue
            if target_date is None or ticker_date != target_date:
                continue

        # Build output record from stored data dict
        record = dict(data)
        record.setdefault('ticker', ticker)
        record.setdefault('side', side)
        record['market_id'] = ticker   # compatibility alias for crypto_1d callers
        results.append(record)

    return results
```

---

## Placement

Insert the new function directly after `get_tracked()` and before `is_tracked()` in `position_tracker.py`:

```
... (existing code) ...
def get_tracked() -> dict:
    ...

def get_active_positions(asset=None, settlement_date=None) -> list[dict]:   # ← INSERT HERE
    ...

def is_tracked(ticker: str, side: str) -> bool:
    ...
```

---

## Callers

| File | Line | Call | Impact |
|------|------|------|--------|
| `agents/ruppert/trader/crypto_1d.py` | 667 | `get_active_positions(asset=asset, settlement_date=settlement_date)` | Will now succeed and use fast in-memory path instead of falling back to trade-log scan |

No other callers currently exist. No existing call sites break (all kwargs are optional).

---

## Edge Cases

| Case | Expected behaviour |
|------|--------------------|
| `get_active_positions()` (no args) | Returns all tracked positions |
| `asset='BTC'` on ticker `KXBTC2026-26MAR31-B90000` | Match (contains 'BTC') |
| `asset='ETH'` on ticker `KXBTC2026-26MAR31-B90000` | No match |
| `settlement_date='2026-03-31'` on ticker without date pattern | Skip (no match) |
| `settlement_date='invalid'` | `target_date=None`; all positions filtered out |
| Both filters provided | AND logic — both must match |
| `_tracked` is empty | Returns `[]` |

---

## Testing Checklist (for QA)

- [ ] `get_active_positions()` returns all tracked positions (no args)
- [ ] `get_active_positions(asset='BTC')` returns only BTC-ticker positions
- [ ] `get_active_positions(settlement_date='2026-03-31')` returns only positions settling 2026-03-31
- [ ] Both filters combined returns intersection
- [ ] Invalid `settlement_date` returns empty list (does not crash)
- [ ] `crypto_1d.py` no longer hits the `except (ImportError, TypeError)` fallback path
- [ ] `get_tracked()` and `is_tracked()` behaviour unchanged
