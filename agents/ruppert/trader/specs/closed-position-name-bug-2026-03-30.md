# Spec: Closed Position Name Bug — 2026-03-30

**Author:** Data Scientist (Ruppert)  
**Status:** Ready for Dev  
**Priority:** Low (display only — no financial impact)

---

## Observed Fact

When a `crypto_15m` trade is open, it displays a human-readable name in the Open Positions table (e.g., `DOGE 15m UP 11:30 PDT`). When the position settles and moves to the Closed Positions table, the name changes to a generic label (e.g., `DOGE 15m direction`, `BTC 15m direction`, `ETH 15m direction`, `XRP 15m direction`).

---

## Root Cause

The name divergence is caused by two different code paths using different field sources for the display title:

### Open Positions path (`/api/positions/active` and `_build_state()`)

```python
raw_title = (t.get('title') or ticker).replace('**', '')
_win_time = _parse_15m_window_time(ticker)
if _win_time:
    raw_title = re.sub(r'\s+\d{4}-\d{2}-\d{2}\b', '', raw_title).strip()
    raw_title = f"{raw_title} {_win_time}"
```

This path:
1. Reads `title` from the trade log record (the original logged value).
2. Detects if the ticker is a 15M market.
3. **Strips the date portion** from the title.
4. **Appends the PDT window time** derived from the ticker (e.g., `11:30 PDT`).

Result: `"DOGE 15m UP 11:30 PDT"` ✅

### Closed Positions path (`/api/trades`)

```python
t['module'] = classify_module(t.get('source', 'bot'), ticker)
closed.append(t)
```

This path:
1. Reads `title` from the trade log record **as-is**.
2. **Does NOT apply** `_parse_15m_window_time()` or the date-stripping logic.
3. Does **not call** `_translate_15m_side()` either.

The raw `title` in the trade log for a `crypto_15m` position appears to be stored generically (e.g., `"DOGE 15m direction"`) — likely because at entry-log time the direction/side was not yet embedded in the title field, or the title field stored by the trader reflects a template rather than a resolved string.

Result: `"DOGE 15m direction"` ❌

---

## BEFORE / AFTER Spec

### BEFORE (current behavior)

| Table           | Name shown              |
|-----------------|-------------------------|
| Open Positions  | `DOGE 15m UP 11:30 PDT` |
| Closed Positions| `DOGE 15m direction`    |

The `/api/trades` endpoint returns the raw `title` field from the trade log without applying the 15M display transformation.

### AFTER (desired behavior)

| Table           | Name shown              |
|-----------------|-------------------------|
| Open Positions  | `DOGE 15m UP 11:30 PDT` |
| Closed Positions| `DOGE 15m UP 11:30 PDT` |

Both tables must produce the same display title for the same position.

---

## Required Change

**File:** `environments/demo/dashboard/api.py`  
**Function:** `get_trades()` (the `/api/trades` endpoint)

Apply the same 15M title transformation that already exists in `get_active_positions()` and `_build_state()`.

### Pseudocode for the fix

In `get_trades()`, after assembling the closed position record `t` and before `closed.append(t)`, add:

```python
# Apply 15M display title transformation (mirrors open positions path)
raw_title = (t.get('title') or ticker).replace('**', '')
_win_time = _parse_15m_window_time(ticker)
if _win_time:
    import re as _re
    raw_title = _re.sub(r'\s+\d{4}-\d{2}-\d{2}\b', '', raw_title).strip()
    raw_title = f"{raw_title} {_win_time}"
t['title'] = raw_title

# Also apply side translation for 15M contracts (yes→UP, no→DOWN)
t['side'] = _translate_15m_side(ticker, t.get('side', 'no'))
```

Both `_parse_15m_window_time()` and `_translate_15m_side()` are already defined at module scope in `api.py`. No new imports or helpers needed.

---

## Scope

- **Affected endpoint:** `GET /api/trades` (Closed Positions table)
- **Not affected:** `/api/positions/active`, `/api/state` (already correct)
- **Risk:** Display only — no financial calculations touched
- **Test:** Open a `crypto_15m` position → let it settle → confirm Closed Positions shows the same name format as Open Positions did

---

## Notes

- The `side` field in closed records also needs `_translate_15m_side()` applied — currently Closed Positions would show `yes`/`no` instead of `UP`/`DOWN` for direction contracts.
- The root `title` stored in the trade log is likely a template string (`"DOGE 15m direction"`) set at logging time before direction resolution. The fix does not require changing the logger — only the display path in `api.py`.
