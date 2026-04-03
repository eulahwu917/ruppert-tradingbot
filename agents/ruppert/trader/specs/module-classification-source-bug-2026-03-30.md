# Spec: Module Misclassification When Exit Source is `ws_position_tracker`

**Date:** 2026-03-30  
**Author:** Trader (Ruppert)  
**Severity:** Medium — P&L appears in header totals but is silently missing from module cards  
**File:** `environments/demo/dashboard/api.py`  
**Function:** `_build_state()`

---

## Problem Statement

When a trade is closed by `ws_position_tracker` (e.g., a live crypto position settled by the websocket monitor), the close record written to the trade log has `source='ws_position_tracker'`. 

In `_build_state()`, there are **two locations** where the trade's source is derived for module classification. Both currently prefer the **exit/close record's source** over the **opening entry's source**:

```python
src = exit_records[ticker].get('source', t.get('source', 'bot')) if ticker in exit_records else t.get('source', 'bot')
```

`exit_records[ticker].get('source', ...)` resolves to `'ws_position_tracker'` when a websocket-driven close record is present. Since `'ws_position_tracker'` matches no module pattern in `classify_module()`, the trade is bucketed as `'other'` and excluded from all module cards (crypto, weather, etc.) — while still contributing to the header Closed P&L total.

**Observed impact at time of audit:** $49.05 missing from the crypto module card.

---

## Root Cause

The exit record's `source` field records *how* a trade was closed (which system triggered the exit), not *what module opened it*. Module classification must always be based on the opening entry's source.

---

## Affected Lines

There are **two identical patterns** to fix in `_build_state()`:

**Occurrence 1** — `settled_tickers` loop (~line 910):
```python
src = exit_records[ticker].get('source', t.get('source', 'bot')) if ticker in exit_records else t.get('source', 'bot')
```

**Occurrence 2** — second `settled_tickers` loop for `_build_state()` module bucketing (~line 1336):
```python
src = (exit_records[ticker].get('source', t.get('source', 'bot'))
       if ticker in exit_records else t.get('source', 'bot'))
```

---

## Fix

Always use the **opening entry's source** (`t.get('source', 'bot')`) for module classification. The exit record's source is irrelevant for this purpose.

---

## BEFORE

**Occurrence 1 (~line 910):**
```python
src = exit_records[ticker].get('source', t.get('source', 'bot')) if ticker in exit_records else t.get('source', 'bot')
```

**Occurrence 2 (~line 1336):**
```python
src = (exit_records[ticker].get('source', t.get('source', 'bot'))
       if ticker in exit_records else t.get('source', 'bot'))
```

---

## AFTER

**Occurrence 1 (~line 910):**
```python
src = t.get('source', 'bot')
```

**Occurrence 2 (~line 1336):**
```python
src = t.get('source', 'bot')
```

---

## Rationale

`t` is the **opening trade entry** for the settled ticker. Its `source` field records the module that placed the trade (e.g., `'crypto'`, `'weather'`, `'bot'`). The exit record (from `ws_position_tracker` or any other closer) tells us the *mechanism* of exit, which is irrelevant to module classification. Using `t.get('source', 'bot')` directly is correct, unambiguous, and consistent with how open trades are classified elsewhere in `_build_state()` (e.g., line 1005, line 1047).

---

## Testing Checklist

- [ ] A trade opened by the crypto module and closed by `ws_position_tracker` appears in the **crypto** module card (not `other`)
- [ ] Header Closed P&L total matches the sum of all module card Closed P&L values (no phantom `other` leakage)
- [ ] Trades opened by `manual`/`economics`/`geo` sources still classify correctly
- [ ] `classify_module(src, ticker)` is never passed `'ws_position_tracker'` as `src`
