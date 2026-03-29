# SA-3 Developer — Module Card Polish
_Completed: 2026-03-13_

## Task
Polish the Weather / Crypto / Fed Module Performance Cards with a new 2-row layout and add `open_pnl` per module to the `/api/pnl` backend response.

---

## Files Modified

| File | Change |
|------|--------|
| `dashboard/api.py` | Added `open_pnl` per module to `/api/pnl` response |
| `dashboard/templates/index.html` | Redesigned module cards (new 2-row layout, inline dropdown, Open P&L column) |

---

## Backend Changes (api.py)

### What changed
- `module_open_stats` now initialized with `open_pnl: 0.0` (was only `open_deployed` and `open_trades`)
- The initialization loop (deployed/trades) was moved BEFORE the open P&L API loop
- In the open P&L loop, after classifying a bot position's source, it now also classifies the module and accumulates `open_pnl` per module
- Removed the old separate `module_open_stats` loop that ran after the open P&L loop (now merged)
- Added `'open_pnl': round(module_open_stats[mod]['open_pnl'], 2)` to `modules_out` dict

### Important note on open_pnl accuracy
`open_pnl` per module IS computed from live Kalshi prices (the open positions loop already calls the Kalshi API for each open position). It is **not** a placeholder — it uses the same `(cur_p - entry_p) * contracts / 100` formula as the total `open_pnl_total`. Values will be `0.0` only when there are no open positions for that module, which is correct.

---

## Frontend Changes (index.html)

### New card structure (all 3 modules: Weather / Crypto / Fed)
```
┌─ [colored left border] ──────────────────────────────┐
│  🌤 Weather                                          │ ← top bar: icon + name only
├──────────────────────────────────────────────────────┤
│  Open P&L  │  Closed P&L [Month▾]  │  Win Rate      │ ← Row 1 (3 equal cols, | dividers)
│  +$0.00    │  +$9.33               │  71%            │
├──────────────────────────────────────────────────────┤
│  Open Deployed  │  Open Trades  │  Total Trades      │ ← Row 2 (3 equal cols, | dividers)
│  $0.00          │  0            │  7                 │
└──────────────────────────────────────────────────────┘
```

### Key decisions
- **Left border** (not top border) — changed from `border-top:3px solid` to `border-left:3px solid` per spec
  - Weather: `#4ade80` (green)
  - Crypto: `#a78bfa` (purple)
  - Fed: `#60a5fa` (blue)
- **Period dropdown** moved from top-right of card → inline next to "Closed P&L" label in Row 1
  - Options: Month / Year / All Time
  - Controls Closed P&L value only (Open P&L and Win Rate are always all-time/current)
- **Open P&L**: new column; colored green/red via `pcls()` helper; sourced from `d.open_pnl` from API
- **Win Rate**: always green (`#4ade80`) regardless of value (removed the `>= 50 ? green : red` conditional)
- **Dividers**: CSS `border-right: 1px solid #222` on first two columns of each row
- **Mobile**: Added `#module-cards-row { grid-template-columns: 1fr !important; }` inside `@media (max-width: 768px)` — cards stack vertically; 2-row layout within each card is unaffected

### JS function updated: `renderModuleCard(mod)`
- Added `openPnlEl` handling for `pfx + '-open-pnl'`
- Win Rate color hardcoded to `#4ade80` (green always)
- Removed `trEl` handling for `pfx + '-trades'` (period-filtered count below winrate — no longer in layout)
- Removed `pctEl` handling for `pfx + '-pnl-pct'` (cost-basis % display — element no longer in HTML)

---

## Git Status
- Both files staged with `git add`
- **NOT pushed** — CEO pushes EOD per workflow rules

---

## TODOs / Notes for QA
1. **Visual verify**: Dashboard should be live at `http://192.168.4.31:8765` — check the 3 module cards render correctly with new layout
2. **open_pnl live data**: Will show real values once there are open positions; currently shows `+$0.00` if no open positions (correct)
3. The old `weather-pnl-pct`, `crypto-module-pnl-pct`, `fed-pnl-pct` elements are gone from HTML — JS guard `if (pctEl)` prevents any errors
4. The old `weather-trades`, `crypto-module-trades`, `fed-trades` elements are gone from HTML — no longer referenced in JS
