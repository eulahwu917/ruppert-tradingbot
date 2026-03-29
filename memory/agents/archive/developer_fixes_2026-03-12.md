# Developer Fixes — 2026-03-12
**SA-3 Developer | QA Report: qa_report_2026-03-12b.md**

---

## Fixes Applied

### W1 — Buying Power Race Condition (`dashboard/templates/index.html`)
**Fix:** In `loadAll()`, changed `loadClosedPnl()` from running in parallel to running sequentially *before* `Promise.all([loadAccount(), ...])`. This guarantees `window._closedPnl` is always set before `loadAccount()` reads it to compute buying power.

```javascript
// Before
async function loadAll(){
  await Promise.all([loadAccount(), loadPositions(), loadTrades(), loadScouts(), loadClosedPnl()]);
}

// After
async function loadAll(){
  await loadClosedPnl();  // must complete first so window._closedPnl is set
  await Promise.all([loadAccount(), loadPositions(), loadTrades(), loadScouts()]);
}
```

### W6 — Midnight Crossover Bug (`dashboard/api.py` — `is_settled_ticker()`)
**Fix:** Replaced the wrapping-hour comparison (`(_dt.utcnow().hour - 4) % 24`) with a proper full-datetime comparison using EDT datetime objects. Constructs `now_edt` and `settle_edt` as `datetime` objects and compares them directly.

```python
# Before
import time as _time
now_hour_edt = (_dt.utcnow().hour - 4) % 24
if now_hour_edt >= hour:
    return True

# After
from datetime import datetime as _dt, timedelta as _td
now_edt = _dt.utcnow() - _td(hours=4)
settle_edt = _dt(mkt_date.year, mkt_date.month, mkt_date.day, hour)
if now_edt >= settle_edt:
    return True
```

### W3 — Dead Variable (`dashboard/api.py` line ~278)
**Fix:** Removed `closed_pnl_realized = 0.0` from the demo branch of `get_account()`. It was assigned but never referenced — leftover from a reverted approach.

### W4 — Unused Import (`dashboard/api.py` — `is_settled_ticker()`)
**Fix:** Removed `import time as _time` from inside `is_settled_ticker()`. The W6 fix supersedes the old code block entirely; `_time` was never used. (Note: a separate `import time as _time` remains in `get_crypto_scan()` at line ~805 where it IS used — that one was NOT touched.)

### W5 — Duplicate Dict Keys (`dashboard/api.py` — `get_account()`)
**Fix:** Removed the first (unrounded) occurrences of `starting_capital`, `bot_deployed`, and `manual_deployed` from the return dict. The second occurrences (rounded values) are kept, which is what the frontend should receive.

---

## Files Modified
- `kalshi-bot/dashboard/api.py`
- `kalshi-bot/dashboard/templates/index.html`

## Git Status
Both files staged (`git add`). Not pushed — awaiting CEO review per rules.

---

## Not Fixed (Out of Scope / Not Assigned)
- **W2** — Open P&L shows `--` when no positions — not in task scope
- **W7** — UTC-4 hardcoded (EST/winter issue) — not in task scope; flagged for future pass

---

*Completed: 2026-03-12 | SA-3 Developer*
