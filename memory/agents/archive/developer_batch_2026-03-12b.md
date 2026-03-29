# Developer Batch Summary — 2026-03-12b
_SA-3 Developer_

## Task Completed

**Sort closed positions table newest to oldest** in `dashboard/templates/index.html`.

### Change Made

**File:** `dashboard/templates/index.html`  
**Function:** `loadTrades()`

Added a `.sort()` call on the `trades` array immediately after the empty-check guard and before the `tb.innerHTML = trades.map(...)` render. Sort logic:

```javascript
// Sort newest to oldest (timestamp preferred, fall back to _date)
trades.sort((a, b) => {
  const da = a.timestamp || a._date || '';
  const db = b.timestamp || b._date || '';
  return db.localeCompare(da);
});
```

- Uses `timestamp` field if present (ISO datetime string, e.g. `"2026-03-12T15:30:00"`)
- Falls back to `_date` field (matches the `dt` variable already used for display)
- String `localeCompare` works correctly for ISO date/datetime strings (lexicographic = chronological)
- `db.localeCompare(da)` → descending order (newest first)

### Git Status

- Staged: `dashboard/templates/index.html` (`git add` done)
- Not pushed — CEO will push end of day

## Issues / Notes

None. Minimal, surgical change. No other files touched.
