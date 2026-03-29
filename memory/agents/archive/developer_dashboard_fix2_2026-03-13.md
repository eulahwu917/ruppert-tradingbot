# Developer Summary — Dashboard Fix 2
_SA-3 Developer | 2026-03-13_

## Commit
`98f45b7` — `dashboard: Fix 1/2/3 - bot-only metrics, remove Bot Perf card, module open stats`

## Files Modified
- `dashboard/api.py`
- `dashboard/templates/index.html`

---

## Fix 1 — Account Level: BOT-only metrics

**Problem:** Account-level Closed P&L ($80.63), Win Rate (60%), and Total Trades included manual/economics/geo trades, diverging ~$6.70 from Bot Performance ($87.33).

**Changes in `api.py` `/api/pnl`:**
- Added `bot_wins` counter (alongside existing `closed_wins`)
- `"closed_pnl"` → now `closed_by_source['bot']` (was `closed_pnl_total`)
- `"closed_win_rate"` → `bot_wins / closed_count_by_source['bot']` (was all-source)
- `"total_trades"` new key → `closed_count_by_source['bot']`
- `total_pnl` = `open_pnl_total + closed_by_source['bot']`
- Chart points use `bot_closed_pnl` (not total)
- `pnl_cache.json` now writes bot-only closed_pnl (used by bot internals)

**Changes in `api.py` `/api/account`:**
- Demo mode buying_power now reads `pnl_cache.json` for `_bot_closed_cached`
- `buying_power = max(STARTING_CAPITAL + _bot_closed_cached - total_deployed, 0)`
- Frontend JS also correct: `window._closedPnl` = `pnl.closed_pnl` (now bot-only)

---

## Fix 2 — Remove Bot Performance Card

**HTML removed:** Entire `<!-- Bot Performance summary -->` div with `split-row` class containing `bot-pnl`, `bot-dep`, `bot-cnt` elements.

**JS removed:**
- `window._botCpnlFrame = 'month'` state variable
- `window._botCpnlData = {...}` state variable
- `function setBotCpnlFrame(frame)` function
- `setSplitPnl('bot-pnl', 'bot-pnl-pct', ...)` call in `loadClosedPnl()`
- `if ($('bot-dep'))` and `if ($('bot-cnt'))` update lines in `loadClosedPnl()`
- Stale comment referencing `bot-pnl`

---

## Fix 3 — Module Cards: Open Capital Deployed, Open Trades, Total Trades

**Backend** (`/api/pnl`):
- Added `module_open_stats` dict computed from `open_tickers` (bot sources only)
- Each module in `modules_out` now includes `open_deployed` (float) and `open_trades` (int)

**Frontend HTML** — added 3-column row inside each card (below P&L / Win Rate):
| Element ID | Field |
|---|---|
| `weather-open-dep` / `crypto-module-open-dep` / `fed-open-dep` | Open Capital Deployed |
| `weather-open-cnt` / `crypto-module-open-cnt` / `fed-open-cnt` | Open Trades |
| `weather-total-trades` / `crypto-module-total-trades` / `fed-total-trades` | Total Trades |

**Frontend JS** — `renderModuleCard()` updated to populate:
- `openDepEl.textContent = dollar(d.open_deployed || 0)`
- `openCntEl.textContent = d.open_trades`
- `totalTrEl.textContent = (d.trade_count || 0) + (d.open_trades || 0)` (all-time)

---

## QA Warning Fixes (Batch 2b)

SA-3 fixed all 4 QA warnings: W1 — added `bot_closed_pnl_month`/`bot_closed_pnl_year` keys to `/api/pnl` and wired `loadClosedPnl()` account bar period selector to use them (bot-only month/year); W2 — removed ~50 lines of dead `.split-*` CSS (main + responsive blocks); W3 — removed dead `setSplitPnl()` JS function (no callers remaining); W4 — fixed `total_pnl = closed_by_source['bot'] + open_by_source['bot']` (was mixing all-source open with bot-only closed). Both files staged.

## Notes
- `closed_pnl_total` variable still exists internally in api.py (used for `closed_by_period` breakdowns like `closed_pnl_month/year`) — NOT changed
- `bot_closed_all` / `bot_closed_month` etc. in pnl response unchanged (still available if needed)
- No git push — staged and committed per rules; CEO pushes EOD
