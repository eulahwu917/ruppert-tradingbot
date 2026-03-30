# Settlement Fix Spec — 2026-03-30

**Author:** Data Scientist (Ruppert)  
**Date:** 2026-03-30  
**Priority:** High — 6 expired positions stuck as open; distorting drift checks and exposure calculations

---

## Context

Six weather positions bought on 2026-03-28 expired 2026-03-29. They are all "B" (between-band) positions on high-temp markets (`KXHIGH*`), side `yes`. No `settle` records exist for them in `trades_2026-03-29.jsonl`. No `entry_price` key is present in any of the 6 buy records. The positions continue to appear as open in `get_open_positions_from_logs()` because no settle/exit record cancels them.

**Truth data check:** `environments/demo/logs/truth/settled_prices.json` contains no entries with `26MAR29` in the key. Outcome is unknown. All settlements must be marked `_manual_settle: true` pending real NWS data.

---

## Fix 1: Write 6 Settlement Records

### Problem
`environments/demo/logs/trades/trades_2026-03-29.jsonl` has no `action: settle` records for these 6 positions. The settlement checker skipped them — likely because `entry_price` was absent and parsing failed silently.

### Schema (from existing settle records in `trades_2026-03-29.jsonl`)
```json
{
  "trade_id": "<uuid>",
  "timestamp": "2026-03-29T<time>-07:00",
  "date": "2026-03-29",
  "entry_date": "2026-03-28",
  "ticker": "...",
  "title": "...",
  "side": "yes",
  "action": "settle",
  "action_detail": "SETTLE LOSS @ 1c",
  "source": "settlement_checker",
  "module": "weather",
  "settlement_result": "no",
  "pnl": null,
  "entry_price": <fill_price_cents>,
  "exit_price": 1,
  "contracts": <N>,
  "size_dollars": <N * fill_price / 100>,
  "fill_price": 1,
  "entry_edge": null,
  "confidence": <from buy record>,
  "hold_duration_hours": 15.0,
  "order_result": {"dry_run": true, "status": "settled"},
  "_manual_settle": true,
  "_outcome_unknown": true
}
```

**Notes on unknown fields:**
- `settlement_result`: unknown — use `"unknown"` (not `"yes"` or `"no"`)
- `pnl`: null — cannot compute without outcome
- `action_detail`: use `"SETTLE UNKNOWN @ ?c"` to signal manual entry
- `exit_price`: null — unknown
- `fill_price` in settle record: null (no exit fill occurred)
- `entry_edge` and `confidence`: copy from buy record

### BEFORE
`trades_2026-03-29.jsonl` contains zero settle records for these 6 tickers.

### AFTER — Exact JSON records to append to `environments/demo/logs/trades/trades_2026-03-29.jsonl`

Append these 6 lines (one JSON object per line):

```jsonl
{"trade_id": "settle-a73da7f6-manual", "timestamp": "2026-03-29T23:59:00-07:00", "date": "2026-03-29", "entry_date": "2026-03-28", "ticker": "KXHIGHTSEA-26MAR29-B46.5", "title": "Will the maximum temperature be  46-47\u00b0 on Mar 29, 2026?", "side": "yes", "action": "settle", "action_detail": "SETTLE UNKNOWN @ ?c", "source": "settlement_checker", "module": "weather", "settlement_result": "unknown", "pnl": null, "entry_price": 43.0, "exit_price": null, "contracts": 232, "size_dollars": 100.11, "fill_price": null, "entry_edge": null, "confidence": 0.7235, "hold_duration_hours": 29.0, "order_result": {"dry_run": true, "status": "settled"}, "_manual_settle": true, "_outcome_unknown": true}
{"trade_id": "settle-e8dd9a32-manual", "timestamp": "2026-03-29T23:59:00-07:00", "date": "2026-03-29", "entry_date": "2026-03-28", "ticker": "KXHIGHMIA-26MAR29-B79.5", "title": "Will the **high temp in Miami** be 79-80\u00b0 on Mar 29, 2026?", "side": "yes", "action": "settle", "action_detail": "SETTLE UNKNOWN @ ?c", "source": "settlement_checker", "module": "weather", "settlement_result": "unknown", "pnl": null, "entry_price": 33.0, "exit_price": null, "contracts": 303, "size_dollars": 100.11, "fill_price": null, "entry_edge": null, "confidence": 0.9007, "hold_duration_hours": 29.0, "order_result": {"dry_run": true, "status": "settled"}, "_manual_settle": true, "_outcome_unknown": true}
{"trade_id": "settle-c88ccd62-manual", "timestamp": "2026-03-29T23:59:00-07:00", "date": "2026-03-29", "entry_date": "2026-03-28", "ticker": "KXHIGHTSFO-26MAR29-B77.5", "title": "Will the maximum temperature be  77-78\u00b0 on Mar 29, 2026?", "side": "yes", "action": "settle", "action_detail": "SETTLE UNKNOWN @ ?c", "source": "settlement_checker", "module": "weather", "settlement_result": "unknown", "pnl": null, "entry_price": 26.0, "exit_price": null, "contracts": 385, "size_dollars": 100.11, "fill_price": null, "entry_edge": null, "confidence": 1.0, "hold_duration_hours": 29.0, "order_result": {"dry_run": true, "status": "settled"}, "_manual_settle": true, "_outcome_unknown": true}
{"trade_id": "settle-755bdfd3-manual", "timestamp": "2026-03-29T23:59:00-07:00", "date": "2026-03-29", "entry_date": "2026-03-28", "ticker": "KXHIGHTDC-26MAR29-B60.5", "title": "Will the maximum temperature be  60-61\u00b0 on Mar 29, 2026?", "side": "yes", "action": "settle", "action_detail": "SETTLE UNKNOWN @ ?c", "source": "settlement_checker", "module": "weather", "settlement_result": "unknown", "pnl": null, "entry_price": 26.0, "exit_price": null, "contracts": 385, "size_dollars": 100.11, "fill_price": null, "entry_edge": null, "confidence": 0.7231, "hold_duration_hours": 29.0, "order_result": {"dry_run": true, "status": "settled"}, "_manual_settle": true, "_outcome_unknown": true}
{"trade_id": "settle-111c25af-manual", "timestamp": "2026-03-29T23:59:00-07:00", "date": "2026-03-29", "entry_date": "2026-03-28", "ticker": "KXHIGHAUS-26MAR29-B84.5", "title": "Will the **high temp in Austin** be 84-85\u00b0 on Mar 29, 2026?", "side": "yes", "action": "settle", "action_detail": "SETTLE UNKNOWN @ ?c", "source": "settlement_checker", "module": "weather", "settlement_result": "unknown", "pnl": null, "entry_price": 27.0, "exit_price": null, "contracts": 370, "size_dollars": 100.11, "fill_price": null, "entry_edge": null, "confidence": 0.6755, "hold_duration_hours": 29.0, "order_result": {"dry_run": true, "status": "settled"}, "_manual_settle": true, "_outcome_unknown": true}
{"trade_id": "settle-dc26d966-manual", "timestamp": "2026-03-29T23:59:00-07:00", "date": "2026-03-29", "entry_date": "2026-03-28", "ticker": "KXHIGHTLV-26MAR29-B89.5", "title": "Will the maximum temperature be  89-90\u00b0 on Mar 29, 2026?", "side": "yes", "action": "settle", "action_detail": "SETTLE UNKNOWN @ ?c", "source": "settlement_checker", "module": "weather", "settlement_result": "unknown", "pnl": null, "entry_price": 19.0, "exit_price": null, "contracts": 526, "size_dollars": 100.11, "fill_price": null, "entry_edge": null, "confidence": 0.9733, "hold_duration_hours": 29.0, "order_result": {"dry_run": true, "status": "settled"}, "_manual_settle": true, "_outcome_unknown": true}
```

**Post-append validation:** After appending, run `get_open_positions_from_logs()` and confirm these 6 tickers no longer appear.

**Follow-up:** When NWS Climatological Reports for Mar 29 are available, update the 6 records: set `settlement_result`, compute `pnl` (`(exit_price - entry_price) * contracts / 100`), set `exit_price` (99 for yes-win, 1 for yes-loss), and remove `_outcome_unknown`.

---

## Fix 2: Expiry Filter in Drift Check

**File:** `agents/ruppert/data_scientist/data_agent.py`  
**Function:** `get_open_positions_from_logs()`

### Problem
The function returns all positions with no settle/exit record — regardless of whether the ticker's market has already expired. Positions for past-dated markets (e.g. `KXHIGHTSEA-26MAR29-*`) keep appearing as open because the expiry date is never checked.

### BEFORE (lines ~367–391)
```python
def get_open_positions_from_logs() -> list[dict]:
    ...
    entries = {}   # (ticker, side) -> aggregated record (based on first buy leg)
    exits = set()  # set of (ticker, side) tuples

    for path in _get_trade_files():
        for t in _read_trades_file(path):
            ticker = t.get('ticker', '')
            side = t.get('side', '')
            if not ticker:
                continue
            key = (ticker, side)
            action = t.get('action', 'buy')
            if action in ('exit', 'settle'):
                exits.add(key)
                entries.pop(key, None)
            else:
                if key not in entries:
                    entries[key] = dict(t)
                else:
                    # scale-in accumulation ...

    return [rec for key, rec in entries.items() if key not in exits]
```

### AFTER — Add expiry filter before the final return
```python
import re
from datetime import date as _date

def _parse_ticker_expiry(ticker: str) -> _date | None:
    """Parse expiry date from Kalshi weather ticker format.
    
    Example: KXHIGHTSEA-26MAR29-B46.5  ->  date(2026, 3, 29)
    Format: {EVENT}-{YY}{MON}{DD}-{STRIKE}
    """
    MONTH_MAP = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
    }
    m = re.search(r'-(\d{2})([A-Z]{3})(\d{2})-', ticker.upper())
    if not m:
        return None
    try:
        yy, mon_str, dd = int(m.group(1)), m.group(2), int(m.group(3))
        month = MONTH_MAP.get(mon_str)
        if not month:
            return None
        year = 2000 + yy
        return _date(year, month, dd)
    except (ValueError, KeyError):
        return None


def get_open_positions_from_logs() -> list[dict]:
    ...
    # (all existing code unchanged until the return statement)

    # Filter out positions where the ticker's market has already expired
    today = _date.today()
    open_records = []
    for key, rec in entries.items():
        if key in exits:
            continue
        ticker = rec.get('ticker', '')
        expiry = _parse_ticker_expiry(ticker)
        if expiry is not None and expiry < today:
            # Market expired in the past — skip (should have been settled)
            continue
        open_records.append(rec)
    return open_records
```

**Why `expiry < today` not `expiry <= today`:** Markets expire on the expiry date itself, but settlement data may not arrive until the following day. Using strict `<` means the position is still visible as "open" on its expiry day (the day it expires), and is only filtered the morning after. This matches the settlement_checker's own schedule.

---

## Fix 3: entry_price Missing at Write Time

**File:** `agents/ruppert/data_scientist/logger.py`  
**Function:** `build_trade_entry()`

### Problem
`build_trade_entry()` does not write `entry_price` to the log. The field is used by `get_open_positions_from_logs()` for weighted-average cost basis on scale-ins, and is required by `settlement_checker` to compute PnL. When absent, scale-in cost basis silently uses 0, and settlement PnL is wrong.

The `entry_price` value is available at write time as `opportunity['fill_price']` (set by trader.py before calling `log_trade()`).

### BEFORE (lines ~122–151 in `logger.py`, inside `build_trade_entry()` return dict)
```python
    return {
        'trade_id':     str(uuid.uuid4()),
        'timestamp':    opportunity.get('timestamp') or datetime.now().isoformat(),
        'date':         opportunity.get('date') or date.today().isoformat(),
        'ticker':       opportunity['ticker'],
        'title':        opportunity.get('title', opportunity['ticker']),
        'side':         opportunity['side'],
        'action':       action,
        'action_detail': raw_action,
        'source':       source,
        'module':       module,
        'noaa_prob':    opportunity.get('noaa_prob'),
        'market_prob':  opportunity.get('market_prob'),
        'edge':         opportunity.get('edge'),
        'confidence':   opportunity.get('confidence') if opportunity.get('confidence') is not None
                        else abs(opportunity.get('edge') or 0),
        'size_dollars': size,
        'contracts':    contracts,
        'scan_contracts': opportunity.get('scan_contracts'),
        'fill_contracts': opportunity.get('fill_contracts'),
        'scan_price':   opportunity.get('scan_price'),
        'fill_price':   opportunity.get('fill_price'),
        'order_result': order_result,
        ...
    }
```
Note: `entry_price` key is **absent**.

### AFTER — Add `entry_price` to the return dict
```python
    # Resolve entry_price: use explicit entry_price if set, else fall back to fill_price.
    # fill_price is set by trader.py before calling log_trade(), so this is always available
    # for new buys. Cast to float to normalize int/float/string variants.
    _fill = opportunity.get('fill_price')
    _entry = opportunity.get('entry_price')
    entry_price_val = None
    if _entry is not None:
        try:
            entry_price_val = float(_entry)
        except (TypeError, ValueError):
            entry_price_val = None
    if entry_price_val is None and _fill is not None:
        try:
            entry_price_val = float(_fill)
        except (TypeError, ValueError):
            entry_price_val = None

    return {
        'trade_id':     str(uuid.uuid4()),
        'timestamp':    opportunity.get('timestamp') or datetime.now().isoformat(),
        'date':         opportunity.get('date') or date.today().isoformat(),
        'ticker':       opportunity['ticker'],
        'title':        opportunity.get('title', opportunity['ticker']),
        'side':         opportunity['side'],
        'action':       action,
        'action_detail': raw_action,
        'source':       source,
        'module':       module,
        'noaa_prob':    opportunity.get('noaa_prob'),
        'market_prob':  opportunity.get('market_prob'),
        'edge':         opportunity.get('edge'),
        'confidence':   opportunity.get('confidence') if opportunity.get('confidence') is not None
                        else abs(opportunity.get('edge') or 0),
        'entry_price':  entry_price_val,          # ← NEW: was absent
        'size_dollars': size,
        'contracts':    contracts,
        'scan_contracts': opportunity.get('scan_contracts'),
        'fill_contracts': opportunity.get('fill_contracts'),
        'scan_price':   opportunity.get('scan_price'),
        'fill_price':   opportunity.get('fill_price'),
        'order_result': order_result,
        ...
    }
```

**Placement note:** Add `entry_price_val` computation *before* the `return` statement. Insert the `'entry_price': entry_price_val,` line after `'confidence'` and before `'size_dollars'` to keep fields grouped logically (pricing fields together).

**Backwards compat:** `normalize_entry_price()` in logger.py already handles `None` entry_price by falling back to `market_prob * 100`. This fix means new records always carry a real value; old records missing the field continue to use the fallback as before.

---

## Execution Order

1. **Fix 3 first** (logger.py) — prevents recurrence going forward  
2. **Fix 1** (append settle records) — clears the 6 stuck positions immediately  
3. **Fix 2** (expiry filter) — defense-in-depth; prevents next time a settlement is missed  

## QA Checklist

- [ ] After Fix 1: `get_open_positions_from_logs()` returns 0 results for all 6 tickers
- [ ] After Fix 2: Run drift check — no false orphan alerts for expired tickers
- [ ] After Fix 3: Buy a new weather position (dry run); confirm `entry_price` field present in JSONL
- [ ] After Fix 3: Confirm `entry_price` == `fill_price` for a standard single-leg buy
- [ ] After Fix 3: Confirm scale-in weighted average still works (two buys at different prices)

