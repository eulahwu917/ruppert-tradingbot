# QA Report — Audit2 Fixes — 2026-03-26

**QA Agent:** SA-4  
**Dev Handoff:** `dev-audit2-fixes-2026-03-26.md`  
**Verdict:** ✅ QA PASS WITH WARNINGS

---

## P0 — Critical

### P0-1: `config.py` — Restore `MAX_POSITION_SIZE` and `MAX_DAILY_EXPOSURE`
✅ **VERIFIED**

Both constants are present at module level with correct values and explanatory comments:
```python
MAX_POSITION_SIZE   = 100.0   # P0-1 fix: was deleted; restored for trader.py legacy path
MAX_DAILY_EXPOSURE  = 700.0   # P0-1 fix: was deleted; restored for trader.py legacy path
```
Verified usage in `trader.py` → `_legacy_calculate_position_size()`:
```python
size = min(ideal_size, config.MAX_POSITION_SIZE)
remaining_daily = config.MAX_DAILY_EXPOSURE - daily_used
```
No regressions. Adjacent code (e.g. `MAX_POSITION_PCT`, other constants) is intact.

---

### P0-2: `kalshi_client.py` — Fix `__main__` dict access
✅ **VERIFIED**

The `__main__` block correctly uses `.get()`:
```python
for m in markets[:5]:
    print(f"  - {m.get('ticker')}: {m.get('title')}")
```
No attribute-style access (`m.ticker`, `m.title`) present. Fix is correct.

---

### P0-3: `ruppert_cycle.py` — Move `actions_taken` before try block
✅ **VERIFIED**

`actions_taken = []` is initialized before the try block with a comment:
```python
# P0-3 fix: initialize actions_taken BEFORE the try block so it's always in scope.
actions_taken = []
try:
    ...
```
No duplicate `actions_taken = []` inside the try block. The variable is accessible in both the `MODE == 'check'` early exit and the final `summary` dict.

**Minor note (no impact):** The `MODE == 'check'` exit and final `summary` dict still use the defensive guard `if 'actions_taken' in dir() else 0`. Since `actions_taken` is now always initialized before those lines, the guard is permanently True and redundant — but harmless. No action needed.

---

## P1 — Silent Wrong Behavior

### P1-1: `openmeteo_client.py` — Fix `hours_into_day` timezone handling
✅ **VERIFIED**

The rewritten logic in `get_current_conditions()` correctly handles the Open-Meteo API behavior:
```python
dt = datetime.fromisoformat(current_time_str)
if dt.tzinfo is None:
    # Naive string from Open-Meteo = already in city local time
    hours_into_day = dt.hour
else:
    # If somehow tz-aware, convert to city local time
    try:
        import zoneinfo
        city_tz = zoneinfo.ZoneInfo(city["timezone"])
        hours_into_day = dt.astimezone(city_tz).hour
    except Exception:
        hours_into_day = dt.hour
```
The explanatory comment is present. Default fallback is 12 (mid-day). No regressions in adjacent functions (`get_ensemble_probability`, `get_full_weather_signal`).

---

### P1-2: `post_trade_monitor.py` — Key `load_open_positions` by `(ticker, side)` tuple
✅ **VERIFIED**

`load_open_positions()` now correctly uses `(ticker, side)` tuple as key for both `entries_by_key` dict and `exit_keys` set:
```python
key = (ticker, side)
if action == 'exit':
    exit_keys.add(key)
else:
    entries_by_key[key] = rec
return [rec for key, rec in entries_by_key.items() if key not in exit_keys]
```
The comment explains the original bug. No regressions in downstream consumers (`check_weather_position`, `check_crypto_position`, `run_monitor`).

---

### P1-3: `dashboard/api.py` — Add `KXSOL` to `classify_module`
✅ **VERIFIED**

Both `KXSOL` and `KXDOGE` are present in the `classify_module` function:
```python
if src == 'crypto' or (src == 'bot' and (
    t.startswith('KXBTC') or t.startswith('KXETH') or
    t.startswith('KXXRP') or t.startswith('KXSOL') or t.startswith('KXDOGE')
)):
    return 'crypto'
```
Consistent with the handoff note: KXDOGE was already there, KXSOL was the actual gap. Fix is correct.

---

### P1-4: `edge_detector.py` — T-market support in `parse_threshold_from_ticker` and `analyze_market`
✅ **VERIFIED**

**Change 1 — `parse_threshold_from_ticker`:** T-prefix handling is added with correct guard against `TM` prefix:
```python
elif part.startswith('T') and len(part) > 1 and not part.startswith('TM'):
    val = part[1:]
    try:
        return float(val)
    except ValueError:
        pass
```
The `TM` guard prevents false matches on date segments (e.g. `TMIN`, `TM` abbreviations in series tickers if any).

**Change 2 — `analyze_market` fallback classification:**
```python
if market_type == "B_band" and temp_range is None and threshold_f is not None:
    parts = ticker.split('-')
    if len(parts) >= 3:
        band_part = parts[2].upper()
        if band_part.startswith('T') and not band_part.startswith('TM'):
            market_type = "T_upper"
```
Logic is correct. Checks the 3rd segment (index 2) which is the band portion. Both T-market classification paths are consistent with the T-upper soft prior applied later in `analyze_market`.

---

### P1-5: `geo_edge_detector.py` — Confirm `_call_claude` uses subprocess CLI, not API client
✅ **VERIFIED**

The function uses `subprocess.run(['claude', '--print', ...])` — no `anthropic.Anthropic()` import or usage exists in this file. The explanatory comment is present in the docstring:
```
P1-5 note: This function uses the `claude --print` CLI, NOT the Anthropic
Python client (anthropic.Anthropic()). ...
```
None return from `_call_claude` is handled gracefully in all callers (`stage1_classify`, `stage2_estimate`).

---

## P2 — Minor Bugs

### P2-1: `ghcnd_client.py` — Fix off-by-one in `compute_station_bias`
✅ **VERIFIED**

The fixed date range:
```python
# P2-1 fix: start_date was `today - (lookback_days + 1)` which fetched lookback_days+1 days.
end_date   = (date.today() - timedelta(days=1)).isoformat()
start_date = (date.today() - timedelta(days=lookback_days)).isoformat()
```
For `lookback_days=30`: `start_date = today - 30`, `end_date = today - 1`.  
Inclusive range = 30 days. Correct. Previously was 31 days (today - 31 to today - 1).

---

### P2-2: `optimizer.py` — Add explicit KXFED/FOMC check before generic FED/FOMC loop
⚠️ **PASS WITH WARNING**

The fix is present:
```python
# P2-2 fix: explicit KXFED/FOMC check BEFORE the generic FED/FOMC keyword scan
if any(kw in t for kw in ('KXFED', 'FOMC')):
    return "fed"
for kw in ("FED", "FOMC"):
    if kw in t:
        return "fed"
```

**Warning:** The explicit check using substring `'KXFED' in t` is functionally redundant with the generic `'FED' in t` check immediately below, because `'FED'` is a substring of `'KXFED'`. The KXFED ticker would have been classified as 'fed' by the generic loop anyway.

This suggests either: (a) the original bug was in a different location than described (perhaps `detect_module` was not the issue), or (b) the fix was applied pre-emptively for clarity/documentation. The fix causes no regression and the code is now more explicit and readable. **No action required**, but the original audit finding's root cause analysis appears slightly off.

---

### P2-3: `logger.py` — Fix `build_trade_entry` fallback module
✅ **VERIFIED**

The else branch for unknown sources now handles `source == 'bot'` specially:
```python
else:
    # P2-3 fix: avoid setting module = 'bot' (not a valid module in MIN_CONFIDENCE).
    if source == 'bot':
        module = 'weather' if ticker_upper.startswith('KXHIGH') else 'other'
    else:
        module = source  # fallback: use source as module (e.g. 'unknown')
```
`'bot'` is no longer assigned as a module value. KXHIGH tickers with source='bot' get 'weather', all others get 'other'. Both 'weather' and 'other' are valid module names (though 'other' is not in `config.MIN_CONFIDENCE`, it won't crash — it just won't match a known key). This is acceptable.

No regressions. The earlier crypto/fed/econ/geo/manual checks in `build_trade_entry` still run before this fallback, so KXBTC/KXETH/KXFED/etc. are still correctly classified.

---

### P2-4: `economics_scanner.py` — Add stub comment to `find_econ_opportunities`
⚠️ **PASS WITH WARNING**

The stub comment is present at the top of the function body:
```python
# STUB: Economics scanner is disabled pending CME FedWatch integration. Returns [] intentionally.
```

**Warning:** The comment says "Returns [] intentionally" but the function body runs a full scan (fetches BLS/FRED data, iterates all markets). This could mislead future devs into thinking the function is a no-op when it actually makes live HTTP requests. A more accurate comment would be "Returns [] in practice under current config (KXFED disabled, other series rarely meet edge threshold)."

The handoff explicitly acknowledges this nuance (P2-4 note). The function is not broken — it just has a misleading comment. **No blocking issue.**

---

## P3 — Design

### P3-1: `bot/strategy.py` — Normalize direction filter comparison to `.lower()`
✅ **VERIFIED**

In `should_enter()`:
```python
if side.lower() != config.WEATHER_DIRECTION_FILTER.lower():  # P3-1: normalize to lowercase for safety
```
Previously used `.upper()`. Now uses `.lower()` consistently. Correct.

---

### P3-2: `capital.py` — Wrap individual `float()` casts in `get_pnl()` try/except
✅ **VERIFIED**

Each cast is in its own try/except block:
```python
try:
    result['closed'] = round(float(data.get('closed_pnl', 0.0)), 2)
except (TypeError, ValueError) as _e:
    logger.warning(f"[Capital] get_pnl(): invalid closed_pnl value — {_e}")
try:
    result['open'] = round(float(data.get('open_pnl', 0.0)), 2)
except (TypeError, ValueError) as _e:
    logger.warning(f"[Capital] get_pnl(): invalid open_pnl value — {_e}")
result['total'] = round(result['closed'] + result['open'], 2)
```
If `closed_pnl` is corrupted, `result['closed']` stays at 0.0, `open_pnl` is still computed independently, and `total` is computed from whichever values are valid. Correct and safe.

---

## Summary Table

| Fix   | File                       | Status                  |
|-------|----------------------------|-------------------------|
| P0-1  | config.py                  | ✅ VERIFIED              |
| P0-2  | kalshi_client.py           | ✅ VERIFIED              |
| P0-3  | ruppert_cycle.py           | ✅ VERIFIED              |
| P1-1  | openmeteo_client.py        | ✅ VERIFIED              |
| P1-2  | post_trade_monitor.py      | ✅ VERIFIED              |
| P1-3  | dashboard/api.py           | ✅ VERIFIED              |
| P1-4  | edge_detector.py           | ✅ VERIFIED              |
| P1-5  | geo_edge_detector.py       | ✅ VERIFIED              |
| P2-1  | ghcnd_client.py            | ✅ VERIFIED              |
| P2-2  | optimizer.py               | ⚠️ PASS WITH WARNING    |
| P2-3  | logger.py                  | ✅ VERIFIED              |
| P2-4  | economics_scanner.py       | ⚠️ PASS WITH WARNING    |
| P3-1  | bot/strategy.py            | ✅ VERIFIED              |
| P3-2  | capital.py                 | ✅ VERIFIED              |

**Total:** 12 ✅ VERIFIED, 2 ⚠️ PASS WITH WARNING, 0 ❌ FAIL

---

## Warnings Summary

1. **P2-2 (`optimizer.py`):** The explicit KXFED/FOMC check is redundant with the generic `'FED' in t` loop below it. Not a bug, but suggests the original root cause may have been misidentified. Low priority.

2. **P2-4 (`economics_scanner.py`):** Stub comment says "Returns [] intentionally" but the function body actually runs and makes HTTP requests. Misleading to future devs. Low priority — the handoff acknowledges this nuance.

---

## Overall Verdict: QA PASS WITH WARNINGS

All critical (P0) and P1 fixes are correctly implemented. P2 and P3 fixes are present. Two minor warnings in P2-2 and P2-4 — neither is a blocking bug. Bot is safe to continue running under DEMO mode.
