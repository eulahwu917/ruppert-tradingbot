# SA-3 Developer — Module Cards Task Summary
_Completed: 2026-03-12_

## Task
Dashboard redesign — per-module performance cards (Weather / Crypto / Fed).

## What Was Done

### Backend: `dashboard/api.py`

**1. `/api/pnl` — per-module stats added**
- Added `classify_module(src, ticker)` helper inside `get_pnl_history()` that classifies bot trades:
  - `weather` → source='weather' OR (source='bot' AND ticker starts KXHIGH)
  - `crypto`  → source='crypto' OR (source='bot' AND ticker starts KXBTC/KXETH/KXXRP/KXDOGE)
  - `fed`     → source='fed' OR ticker starts KXFED/KXFEDDECISION
  - `other`   → remaining bot-sourced trades
- Added `module_stats` dict tracking per-module: closed_pnl, closed_pnl_month, closed_pnl_year, trade_count, trade_count_month, trade_count_year, wins
- Added `modules_out` computation with win_rate (all-time), rounded values
- `/api/pnl` now returns `"modules": { "weather": {...}, "crypto": {...}, "fed": {...}, "other": {...} }`

**2. `/api/trades` — manual trades filtered from display**
- Added `_MANUAL_EXCL = ('manual', 'economics', 'geo')` filter at end of `get_trades()`
- Source 'manual', 'economics', 'geo' no longer appear in the Closed Positions table

### Frontend: `dashboard/templates/index.html`

**3. Manual Trades card removed**
- Removed entire second `split-card` div (the Manual Trades card showing manual P&L, deployed, trade count)
- Renamed "Bot Trades" → "Bot Performance" on the remaining card

**4. Per-module performance cards added**
- 3 cards side-by-side between the Bot Performance row and the positions table
- 🌤 Weather (green border `#4ade80`), ₿ Crypto (purple border `#a78bfa`), 🏛 Fed (blue border `#60a5fa`)
- Each card shows: Closed P&L (colored), Win Rate (all-time), trade count for period
- Period selector per card: This Month / This Year / All Time
- JS: `MODULE_ID` map, `setModulePeriod(mod, period)`, `renderModuleCard(mod)`
- Note: crypto module card uses id prefix `crypto-module-*` to avoid collision with existing `crypto-*` ids in the crypto scan tab

**5. `loadClosedPnl()` updated**
- After receiving `/api/pnl` data, reads `pnl.modules` and calls `renderModuleCard()` for weather/crypto/fed

## Git
- Commit: `b84d0f5` — "Dashboard: per-module performance cards (Weather/Crypto/Fed) + filter manual from closed trades table"
- Files staged and committed (not pushed — CEO pushes EOD)

## QA Warning Fixes (SA-3, 2026-03-12)
- W1: Fixed weather classification — now requires BOTH (src in weather/bot) AND ticker starts KXHIGH
- W2: Removed dead `t.startswith('KXFEDDECISION')` check from fed classification (already covered by KXFED)
- W3: Removed all orphaned manual card JS: `_manCpnlData`, `_manCpnlFrame`, `setManCpnlFrame()`, and all `man-pnl`/`man-dep`/`man-cnt` updates from `loadClosedPnl()`

## TODOs / Known Gaps
- P&L % return per module card is currently blank — requires per-module cost basis tracking in the backend (not added since cost basis aggregation would need a separate pass; low priority)
- `other` module data is computed in backend but not surfaced in any card (not required by spec)
- `fed` module: no live trades yet (demo mode) — card will show `--` / `0 trades` until bot places fed trades
