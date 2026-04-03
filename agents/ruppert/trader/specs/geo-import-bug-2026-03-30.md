# Spec: Fix Geo Import Bug — `ModuleNotFoundError` in `search_geo_markets()`

**Date:** 2026-03-30
**Author:** Trader (Ruppert)
**Priority:** Critical — Geo scanner has placed 0 trades since launch
**File:** `environments/demo/kalshi_market_search.py`
**Function:** `search_geo_markets()`

---

## Problem

The geo market scanner fails silently on every scan due to a bare import inside `search_geo_markets()`. The import is resolved at call time (not module load time), so the module loads without error but every geo scan raises a `ModuleNotFoundError`, preventing any geo trades from executing.

### Root Cause

**File:** `environments/demo/kalshi_market_search.py`, **line 108**

```python
# BEFORE (broken)
from logger import log_activity
```

Python cannot resolve `logger` as a bare module name from this file's execution context. The correct fully-qualified path within the Ruppert agent tree must be used.

---

## Fix

**File:** `environments/demo/kalshi_market_search.py`, **line 108**

```python
# AFTER (fixed)
from agents.ruppert.data_scientist.logger import log_activity
```

---

## BEFORE / AFTER

### BEFORE

```python
def search_geo_markets(...):
    ...
    from logger import log_activity          # line 108 — BROKEN: ModuleNotFoundError at runtime
    seen_tickers = set()
    all_markets = []
    ...
```

### AFTER

```python
def search_geo_markets(...):
    ...
    from agents.ruppert.data_scientist.logger import log_activity   # line 108 — FIXED
    seen_tickers = set()
    all_markets = []
    ...
```

---

## Scope

- **1 line changed** in 1 file
- No logic changes — pure import path correction
- All downstream `log_activity(...)` call sites in `search_geo_markets()` (lines 122, 144, 148, 150) remain unchanged

---

## Verification

After fix:
1. Import `search_geo_markets` in a Python shell — confirm no `ModuleNotFoundError`
2. Run one geo scan cycle — confirm `log_activity` calls execute and geo markets are returned
3. Confirm geo trades begin flowing through the normal pipeline

---

## Impact

- **Before fix:** 0 geo trades placed (all scans crash before reaching evaluation)
- **After fix:** Geo scanner operates normally; trades flow to Trader for evaluation and execution
