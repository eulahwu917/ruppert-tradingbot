# QA REPORT — Module Card Polish
_SA-4 QA | 2026-03-13_

**Status: PASS WITH WARNINGS**

---

## Files Reviewed
- `kalshi-bot/dashboard/api.py`
- `kalshi-bot/dashboard/templates/index.html`

---

## ✅ Checks Passed

### Backend (api.py)

**1. `open_pnl` present per module in `/api/pnl` response under `modules.{module}`**
Confirmed in `modules_out` dict (inside `get_pnl_history()`):
```python
modules_out[mod] = {
    ...
    'open_pnl': round(module_open_stats[mod]['open_pnl'], 2),
    ...
}
```
Present for all four module keys: `weather`, `crypto`, `fed`, `other`. ✅

**2. `open_pnl` computed from open positions loop using `(cur_p - entry_p) * contracts / 100`**
Confirmed in the open-positions loop:
```python
pnl = round((cur_p - entry_p) * contracts / 100, 2)
...
module_open_stats[mod_open]['open_pnl'] += pnl
```
Same `pnl` value that feeds `open_pnl_total` is accumulated per module. Formula is correct. ✅

**3. No trading logic changed**
Only `dashboard/api.py` and `dashboard/templates/index.html` were modified. No changes to any trading-critical files:
- `bot/strategy.py` — untouched ✅
- `main.py`, `trader.py`, `kalshi_client.py` — untouched ✅
- `openmeteo_client.py`, `edge_detector.py` — untouched ✅
- `crypto_client.py`, `crypto_scanner.py` — untouched ✅
- `bot/position_monitor.py` — untouched ✅

---

### Frontend (index.html)

**1. Each module card has 2 rows of 3 equal-width columns**
All 3 cards (Weather, Crypto, Fed) use `display:flex` with three `flex:1` divs per row. ✅

**2. Row 1: Open P&L | Closed P&L | Win Rate — with pipe dividers**
Confirmed for all 3 cards:
- Col 1 (Open P&L): `border-right:1px solid #222` ✅
- Col 2 (Closed P&L): `border-right:1px solid #222` ✅
- Col 3 (Win Rate): no right border (correct — last column) ✅

**3. Row 2: Open Deployed | Open Trades | Total Trades — with pipe dividers**
Confirmed for all 3 cards, same border pattern. ✅

**4. Closed P&L has inline period dropdown — NOT a card-level dropdown**
The `<select>` is nested inside the label `<div>` alongside "Closed P&L" text, using `display:flex` alignment. Not card-level. ✅

**5. Win Rate is always all-time (not period-filtered)**
Backend: `win_rate` computed from all-time `ms['wins'] / ms['trade_count']` — no period filtering. ✅  
JS `renderModuleCard()`: uses `d.win_rate` directly, no period selector applied. ✅

**6. Open P&L colored green/red correctly**
JS sets `openPnlEl.className = pcls(opnl)` → `pnl-pos` (green) / `pnl-neg` (red) / `pnl-neu` (gray at 0). ✅  
Initial HTML state is `class="pnl-neu"` for `--` placeholder. ✅

**7. Closed P&L colored green/red correctly**
JS sets `pnlEl.className = pcls(pnl)` — same `pcls()` helper. ✅  
Initial HTML state is `class="pnl-neu"`. ✅

**8. Mobile: module cards stack vertically at ≤768px**
```css
@media (max-width: 768px) {
  #module-cards-row { grid-template-columns: 1fr !important; }
}
```
Confirmed present. 2-row layout within each card is unaffected. ✅

**9. No dead JS or HTML from previous card layout**
`renderModuleCard()` contains no references to removed element IDs (`-pnl-pct`, `-trades` without open/total prefix). Old guard pattern (`if (pctEl)`) was fully removed — elements and JS references both gone cleanly. ✅  
Searched HTML for `weather-pnl-pct`, `crypto-module-pnl-pct`, `fed-pnl-pct`, `weather-trades`, `crypto-module-trades`, `fed-trades` — none found. ✅

**10. No old card-level period dropdown remaining**
No card-header-level `<select>` exists. The only top-level period selector is `#cpnl-select` in the Account Bar (expected, pre-existing). ✅

**Card border colors — confirmed correct:**
- Weather: `border-left:3px solid #4ade80` (green) ✅
- Crypto: `border-left:3px solid #a78bfa` (purple) ✅
- Fed: `border-left:3px solid #60a5fa` (blue) ✅

---

## ⚠️ Warnings (discretionary)

**W1 — Dropdown labels: "Month/Year/All Time" vs spec "This Month/This Year/All Time"**
The inline period dropdowns render as `Month | Year | All Time` rather than the longer `This Month | This Year | All Time` from the task spec. Functionality is identical; only cosmetic. CEO may accept as-is given the tight inline space.
- Affected: `#weather-period`, `#crypto-module-period`, `#fed-period`

**W2 — Module `open_pnl` computed server-side; account bar open P&L computed client-side**
Module card open P&L comes from `/api/pnl` (server calls Kalshi API). Account bar open P&L comes from `loadLivePrices()` (client fetches `/api/positions/prices` directly). These are computed independently and may diverge slightly at any given refresh cycle. Not a correctness bug — just an architectural note. No action needed unless exact consistency between the two is required.

**W3 — Win Rate always hardcoded green (`#4ade80`) regardless of value**
This is intentional per the developer's design decision (noted in dev summary). The account bar Win Rate still uses the `>= 50 ? green : red` threshold. Calling out for CEO awareness in case the always-green behavior is reconsidered later.

---

## ❌ Issues (must fix)

None.

---

## Summary

All 10 checklist items pass. No bugs, no dead code, no trading logic touched, no security issues. Three cosmetic/architectural warnings flagged for CEO awareness — none block approval.

**Recommendation: CEO may approve and stage for EOD push.**
