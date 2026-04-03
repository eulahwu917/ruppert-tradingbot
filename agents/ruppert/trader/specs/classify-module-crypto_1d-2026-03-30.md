# Spec: Explicit crypto_1d Source Mapping in classify_module()

**Date:** 2026-03-30  
**Author:** Trader (subagent)  
**Status:** PENDING DEV  
**Priority:** MEDIUM — logging/dashboard correctness; does not affect trade execution

---

## Problem

`classify_module()` in `agents/ruppert/data_scientist/logger.py` has no explicit branch for
`src == 'crypto_1d'`. When a trade logged with `source='crypto_1d'` passes through the
function, it falls through all explicit checks and eventually:

1. Hits `if src == 'crypto_15m' or '15M' in (ticker or '').upper()` (line 450) — misses because `src` is `'crypto_1d'`, not `'crypto_15m'`.
2. Falls to `return 'other'` (line 453).

Result: `crypto_1d` trades are bucketed as `'other'` in the dashboard, daily exposure reports,
and module-scoped cap calculations. This breaks the `CRYPTO_1D_DAILY_CAP_PCT` enforcement chain
if any code path routes through `classify_module()` for bucket lookup.

---

## Affected File

**`agents/ruppert/data_scientist/logger.py`** — function `classify_module()` starting at line 427.

---

## BEFORE

```python
def classify_module(src: str, ticker: str) -> str:
    """Classify a trade into a module bucket based on source and ticker prefix.

    Single source of truth - imported by dashboard/api.py to stay in sync.
    """
    t = (ticker or '').upper()
    if src in ('weather',) or (src in ('weather', 'bot') and t.startswith('KXHIGH')):
        return 'weather'
    if src == 'crypto' or (src in ('crypto', 'bot') and any(
        t.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')
    )):
        return 'crypto'
    if src == 'fed' or t.startswith('KXFED'):
        return 'fed'
    if src == 'econ' or t.startswith('KXCPI'):
        return 'econ'
    if src == 'geo' or any(t.startswith(p) for p in (
        'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
        'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
    )):
        return 'geo'
    if src == 'manual':
        return 'manual'
    if src == 'crypto_15m' or '15M' in (ticker or '').upper():
        return 'crypto'
    return 'other'
```

---

## AFTER

Add `if src == 'crypto_1d': return 'crypto'` **before** the existing `crypto` check
(i.e., before line 435). This ensures the explicit match fires before the prefix-based fallback:

```python
def classify_module(src: str, ticker: str) -> str:
    """Classify a trade into a module bucket based on source and ticker prefix.

    Single source of truth - imported by dashboard/api.py to stay in sync.
    """
    t = (ticker or '').upper()
    if src in ('weather',) or (src in ('weather', 'bot') and t.startswith('KXHIGH')):
        return 'weather'
    if src == 'crypto_1d':                                                   # ← ADD
        return 'crypto'                                                       # ← ADD
    if src == 'crypto' or (src in ('crypto', 'bot') and any(
        t.startswith(p) for p in ('KXBTC', 'KXETH', 'KXXRP', 'KXSOL', 'KXDOGE')
    )):
        return 'crypto'
    if src == 'fed' or t.startswith('KXFED'):
        return 'fed'
    if src == 'econ' or t.startswith('KXCPI'):
        return 'econ'
    if src == 'geo' or any(t.startswith(p) for p in (
        'KXUKRAINE', 'KXRUSSIA', 'KXISRAEL', 'KXIRAN', 'KXTAIWAN',
        'KXNATO', 'KXCHINA', 'KXNKOREA', 'KXCEASEFIRE',
    )):
        return 'geo'
    if src == 'manual':
        return 'manual'
    if src == 'crypto_15m' or '15M' in (ticker or '').upper():
        return 'crypto'
    return 'other'
```

---

## Precise Edit (for Dev)

**File:** `agents/ruppert/data_scientist/logger.py`  
**Location:** Inside `classify_module()`, after the `weather` block, before the `crypto` block.

**Insert after:**
```python
    if src in ('weather',) or (src in ('weather', 'bot') and t.startswith('KXHIGH')):
        return 'weather'
```

**Insert before:**
```python
    if src == 'crypto' or (src in ('crypto', 'bot') and any(
```

**Lines to insert:**
```python
    if src == 'crypto_1d':
        return 'crypto'
```

---

## Why Before the crypto Block?

The existing `crypto` check requires `src in ('crypto', 'bot')`. The string `'crypto_1d'` does
not match `'crypto'`, so it would not be caught even if we added it to the tuple — the logic
checks for exact equality, not prefix. The separate early-return guard is the cleanest fix and
mirrors the `crypto_15m` pattern already at the bottom of the function.

---

## Acceptance Criteria

1. `classify_module('crypto_1d', 'KXBTCD-25JUN5-T90000')` returns `'crypto'`
2. `classify_module('crypto_1d', 'KXETHD-25JUN5-T3000')` returns `'crypto'`
3. `classify_module('crypto_15m', 'KXBTC-15M-...')` still returns `'crypto'` (no regression)
4. `classify_module('crypto', 'KXBTC-...')` still returns `'crypto'` (no regression)
5. `classify_module('other_src', 'SOMETICKET')` still returns `'other'` (no regression)
6. Dashboard module breakdown no longer shows `crypto_1d` trades under `'other'`
