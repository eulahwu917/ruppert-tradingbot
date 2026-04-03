# SPEC: Dashboard Layout Reshuffle — Sports Odds / Crypto Card Changes

**Date:** 2026-04-01
**Author:** Data Scientist
**Status:** Ready for Dev
**Files:** `environments/demo/dashboard/templates/index.html`, `environments/demo/dashboard/api.py`

---

## Change 1: Swap Crypto and Sports Odds Card Positions

**Current layout** (line 278 `#module-cards-row`):
```
Weather | Crypto | Geo | Fed   ← 4-col grid (repeat(4,1fr))
Sports Odds                    ← full-width (grid-column:1/-1)
```

**Target layout:**
```
Weather | Sports Odds | Geo | Fed   ← 4-col grid (repeat(4,1fr))
Crypto                              ← full-width (grid-column:1/-1, see Change 3)
```

### Exact HTML changes

1. **Move the Sports Odds card** (lines 471–482) from its current position (after the Fed card, before the closing `</div>` of `#module-cards-row`) to **between the Weather card and the Geo card** — i.e., where the Crypto card currently sits (lines 328–376).

2. **Remove `grid-column:1/-1`** from the Sports Odds card's outer `<div>`. It should now be a regular 1fr cell within the 4-col grid.

3. **Move the Crypto card** (lines 328–376) to **after the Fed card** (where Sports Odds was). Add `style="grid-column:1/-1;"` to make it full-width. (But see Change 3 — the Crypto card HTML will be entirely replaced.)

4. The `#module-cards-row` grid stays `repeat(4,1fr)`.

### Backend: No changes needed.

### JS: No changes needed for the swap itself.

### Risk/Edge cases
- Mobile CSS override `#module-cards-row { grid-template-columns: 1fr !important; }` (line 195) already collapses to single-column, so the full-width crypto card will naturally stack. No mobile fix needed.

---

## Change 2: Sports Odds → Metric Card Style (No Odds Table)

**Current:** Sports Odds uses `card-head`/`card-body` layout with a `<table class="sports-table">` showing Matchup/Vegas/Kalshi/Gap columns. It's populated by `refreshSports()` (lines 1344–1363) which calls `/api/sports`.

**Target:** Same metric card layout as Weather/Geo/Fed — two rows of stats:
- Row 1: Open P&L | Closed P&L (period selector) | Win Rate
- Row 2: Open Deployed | Open Trades | Total Trades

### Exact HTML changes

Replace the entire Sports Odds card (lines 471–482) with this structure:

```html
<!-- ⚽ Sports Odds -->
<div class="card" style="border-left:3px solid #f59e0b;">
  <div style="padding:16px;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
      <span style="font-size:18px;">⚽</span>
      <span style="font-size:13px;font-weight:700;color:#fff;">Sports Odds</span>
    </div>
    <!-- Row 1: Open P&L | Closed P&L | Win Rate -->
    <div style="display:flex;margin-bottom:14px;">
      <div style="flex:1;padding-right:12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Open P&amp;L</div>
        <div class="pnl-neu" id="sports-open-pnl" style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">--</div>
      </div>
      <div style="flex:1;padding:0 12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;display:flex;align-items:center;justify-content:center;gap:4px;flex-wrap:wrap;">
          Closed P&amp;L
          <select id="sports-period" onchange="setModulePeriod('sports',this.value)" style="font-size:8px;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:3px;color:#666;padding:1px 3px;cursor:pointer;outline:none;">
            <option value="month" selected>This Month</option>
            <option value="year">This Year</option>
            <option value="all">All Time</option>
          </select>
        </div>
        <div class="pnl-neu" id="sports-pnl" style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">--</div>
      </div>
      <div style="flex:1;padding-left:12px;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Win Rate</div>
        <div style="font-size:22px;font-weight:700;color:#888;" id="sports-winrate">--</div>
      </div>
    </div>
    <!-- Row 2: Open Deployed | Open Trades | Total Trades -->
    <div style="display:flex;border-top:1px solid #1a1a1a;padding-top:12px;">
      <div style="flex:1;padding-right:12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Open Deployed</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="sports-open-dep">--</div>
      </div>
      <div style="flex:1;padding:0 12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Open Trades</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="sports-open-cnt">--</div>
      </div>
      <div style="flex:1;padding-left:12px;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Total Trades</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="sports-total-trades">--</div>
      </div>
    </div>
  </div>
</div>
```

Element ID prefix: `sports` (matching convention: `sports-open-pnl`, `sports-pnl`, `sports-winrate`, `sports-open-dep`, `sports-open-cnt`, `sports-total-trades`, `sports-period`).

### Backend changes needed

**Problem:** `/api/state` → `_build_state()` → `modules_out` only returns `weather`, `crypto`, `fed`, `geo` (line 1568). There is **no `sports` module** in `classify_module()` or `get_parent_module()`. Sports Odds currently has zero traded positions — it's just an odds table viewer.

**Required:**

1. **`logger.py` — `classify_module()`:** Add sports classification:
   ```python
   # After geo classification, before return 'other':
   if src == 'sports' or t.startswith('KXSPORT') or t.startswith('KXML') or t.startswith('KXNBA') or t.startswith('KXNFL'):
       return 'sports_odds'
   ```
   *Note:* We need to confirm the actual Kalshi sports ticker prefixes. For now, use source-based classification (`src == 'sports'`).

2. **`logger.py` — `get_parent_module()`:** Add:
   ```python
   if m.startswith('sports'):
       return 'sports'
   ```

3. **`api.py` — `_build_state()`:**
   - Add `'sports'` to `module_keys` (line 1314): `['weather', 'crypto', 'fed', 'geo', 'sports', 'other']`
   - Add `'sports'` to the `for mod` loop that builds `modules_out` (line 1568): `for mod in ['weather', 'crypto', 'fed', 'geo', 'sports']:`

4. **`api.py` — `/api/pnl`:**
   - Add `'sports'` to `module_keys` (line 900): `['weather', 'crypto', 'fed', 'sports', 'other']`

### JS wiring

1. **`MODULE_ID`** (line 545): Add `sports: 'sports'`:
   ```js
   const MODULE_ID = { weather: 'weather', crypto: 'crypto-module', fed: 'fed', geo: 'geo', sports: 'sports' };
   ```

2. **`window._modulePeriod`** (line 548): Add `sports: 'month'`:
   ```js
   window._modulePeriod = { weather: 'month', crypto: 'month', fed: 'month', geo: 'month', sports: 'month' };
   ```

3. **`renderState()`** (line 1190): Add `'sports'` to the forEach loop:
   ```js
   ['weather', 'crypto', 'fed', 'geo', 'sports'].forEach(m => {
   ```

4. **Remove `refreshSports()`** (lines 1344–1363) and remove it from `loadAll()` (line 1368):
   ```js
   // Before:
   await Promise.all([loadTrades(), loadScouts(), refreshSports()]);
   // After:
   await Promise.all([loadTrades(), loadScouts()]);
   ```

5. **Remove** the `sports-ts` ref element and related CSS for `.sports-table` (lines 121–127) — now dead code.

### Risk/Edge cases
- **Sports has zero trades today.** All metrics will show `--` / `$0.00` / `0` — same as Fed/Geo when they have no trades. This is fine.
- The old `/api/sports` endpoint can stay (no harm), but `refreshSports()` should be removed from the JS so we don't call a now-unused endpoint.

---

## Change 3: Crypto Card → Full-Width with Per-Sub-Module Tabs

**Current:** Single crypto metric card (lines 328–376) showing aggregated crypto stats. `classify_module()` already splits crypto into: `crypto_15m_dir`, `crypto_1h_dir`, `crypto_1h_band`. There is no `crypto_1d` — `crypto_1d` maps to `crypto_1h_dir` (the 1D above/below binary on Kalshi actually settles hourly).

**Target:** One full-width card at the bottom of `#module-cards-row` with tabs: **15m Dir | 1H Dir | 1H Band | 1D**. Each tab shows the same metric layout (Open P&L, Closed P&L w/ period selector, Win Rate, Open Deployed, Open Trades, Total Trades).

**Important naming clarification:** The user said "1D" but `classify_module` uses `crypto_1h_dir` for source=`crypto_1d` tickers (KXBTCD, KXETHD, KXSOLD). The tab labels should be:
- **15m Dir** → sub-module `crypto_15m_dir`
- **1H Band** → sub-module `crypto_1h_band`
- **1H Dir** → currently unused (no trades exist with this classification yet)
- **1D** → sub-module `crypto_1h_dir` (source=`crypto_1d`, tickers KXBTCD/KXETHD/KXSOLD)

For clarity in the UI: use the labels David specified (15m Dir, 1H Dir, 1H Band, 1D) and map them to sub-module keys on the backend.

### Exact HTML changes

Replace the existing Crypto card (lines 328–376) with a full-width tabbed card at the end of `#module-cards-row` (after the Fed card, as specified in Change 1):

```html
<!-- ₿ Crypto (full-width, tabbed by sub-module) -->
<div class="card" style="border-left:3px solid #a78bfa;grid-column:1/-1;">
  <div class="tabs" id="crypto-sub-tabs">
    <button class="tab on" onclick="switchCryptoSub('crypto_15m_dir',this)">15m Dir</button>
    <button class="tab" onclick="switchCryptoSub('crypto_1h_dir',this)">1H Dir</button>
    <button class="tab" onclick="switchCryptoSub('crypto_1h_band',this)">1H Band</button>
    <button class="tab" onclick="switchCryptoSub('crypto_1d',this)">1D</button>
  </div>
  <div style="padding:16px;" id="crypto-sub-body">
    <!-- Populated by JS: same 2-row metric layout as other module cards -->
    <!-- Row 1: Open P&L | Closed P&L (period selector) | Win Rate -->
    <div style="display:flex;margin-bottom:14px;">
      <div style="flex:1;padding-right:12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Open P&amp;L</div>
        <div class="pnl-neu" id="crypto-sub-open-pnl" style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">--</div>
      </div>
      <div style="flex:1;padding:0 12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;display:flex;align-items:center;justify-content:center;gap:4px;flex-wrap:wrap;">
          Closed P&amp;L
          <select id="crypto-sub-period" onchange="setCryptoSubPeriod(this.value)" style="font-size:8px;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:3px;color:#666;padding:1px 3px;cursor:pointer;outline:none;">
            <option value="day">Today</option>
            <option value="week">This Week</option>
            <option value="month" selected>This Month</option>
            <option value="year">This Year</option>
            <option value="all">All Time</option>
          </select>
        </div>
        <div class="pnl-neu" id="crypto-sub-pnl" style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">--</div>
      </div>
      <div style="flex:1;padding-left:12px;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Win Rate</div>
        <div style="font-size:22px;font-weight:700;color:#888;" id="crypto-sub-winrate">--</div>
      </div>
    </div>
    <!-- Row 2: Open Deployed | Open Trades | Total Trades -->
    <div style="display:flex;border-top:1px solid #1a1a1a;padding-top:12px;">
      <div style="flex:1;padding-right:12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Open Deployed</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="crypto-sub-open-dep">--</div>
      </div>
      <div style="flex:1;padding:0 12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Open Trades</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="crypto-sub-open-cnt">--</div>
      </div>
      <div style="flex:1;padding-left:12px;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Total Trades</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="crypto-sub-total-trades">--</div>
      </div>
    </div>
  </div>
</div>
```

### Backend changes needed

**Problem:** `/api/state` returns `modules.crypto` as a single aggregated object. It does NOT return per-sub-module breakdowns (`crypto_15m_dir`, `crypto_1h_dir`, `crypto_1h_band`).

**Required changes to `api.py` → `_build_state()`:**

1. **Expand `module_keys`** to include crypto sub-modules:
   ```python
   module_keys = ['weather', 'crypto', 'crypto_15m_dir', 'crypto_1h_dir', 'crypto_1h_band', 'fed', 'geo', 'sports', 'other']
   ```

2. **In the module_open accumulation loop** (lines 1357–1360), use `mod` (the detailed sub-module from `classify_module()`) instead of `parent_mod` when accumulating crypto sub-module stats:
   ```python
   # Accumulate into BOTH parent module and sub-module
   module_open[parent_mod]['open_deployed'] += cost
   module_open[parent_mod]['open_trades']   += 1
   if pnl is not None:
       module_open[parent_mod]['open_pnl'] += pnl
   # Also accumulate into sub-module if it's a crypto sub
   if mod in module_open and mod != parent_mod:
       module_open[mod]['open_deployed'] += cost
       module_open[mod]['open_trades']   += 1
       if pnl is not None:
           module_open[mod]['open_pnl'] += pnl
   ```

3. **Same dual-accumulation pattern for `module_closed`** — when processing settled tickers, accumulate into both `parent_mod_c` and the detailed `mod_c` if it's a crypto sub-module.

4. **Add sub-modules to `modules_out`** (line 1568):
   ```python
   for mod in ['weather', 'crypto', 'crypto_15m_dir', 'crypto_1h_dir', 'crypto_1h_band', 'fed', 'geo', 'sports']:
   ```

5. **Also add `crypto_1d` as an alias** in the response. Since `classify_module` returns `crypto_1h_dir` for source=`crypto_1d` tickers, add after building modules_out:
   ```python
   # Alias: frontend uses 'crypto_1d' tab key for the 1D sub-module
   modules_out['crypto_1d'] = modules_out.get('crypto_1h_dir', modules_out.get('other', {}))
   ```

6. **Same expansion in `/api/pnl`** if the legacy endpoint is still used for fallback.

### JS wiring

1. **Remove the old `'crypto'` entry from `MODULE_ID`** — the aggregated crypto card is gone. The parent-level `renderModuleCard('crypto')` is no longer needed.

2. **Add new state variables:**
   ```js
   window._activeCryptoSub = 'crypto_15m_dir';
   window._cryptoSubPeriod = 'month';
   window._cryptoSubData = {};
   ```

3. **Add `switchCryptoSub()` function:**
   ```js
   function switchCryptoSub(subKey, btn) {
     window._activeCryptoSub = subKey;
     document.querySelectorAll('#crypto-sub-tabs .tab').forEach(t => t.classList.remove('on'));
     btn.classList.add('on');
     renderCryptoSubCard();
   }
   ```

4. **Add `setCryptoSubPeriod()` function:**
   ```js
   function setCryptoSubPeriod(period) {
     window._cryptoSubPeriod = period;
     renderCryptoSubCard();
   }
   ```

5. **Add `renderCryptoSubCard()` function** — reads from `window._cryptoSubData[activeSub]`:
   ```js
   function renderCryptoSubCard() {
     const sub = window._activeCryptoSub;
     const d = window._cryptoSubData[sub];
     if (!d) {
       // Clear all fields to '--'
       ['crypto-sub-open-pnl','crypto-sub-pnl','crypto-sub-winrate',
        'crypto-sub-open-dep','crypto-sub-open-cnt','crypto-sub-total-trades'
       ].forEach(id => { const el = $(id); if(el) el.textContent = '--'; });
       return;
     }
     const period = window._cryptoSubPeriod || 'month';
     const pnl = period === 'day'   ? (d.closed_pnl_day   ?? 0)
               : period === 'week'  ? (d.closed_pnl_week  ?? 0)
               : period === 'month' ? (d.closed_pnl_month ?? 0)
               : period === 'year'  ? (d.closed_pnl_year  ?? 0)
               : d.closed_pnl;

     const opnlEl = $('crypto-sub-open-pnl');
     if (opnlEl) {
       const opnl = d.open_pnl != null ? d.open_pnl : 0;
       opnlEl.className = pcls(opnl);
       opnlEl.style.cssText = 'font-size:22px;font-weight:700;letter-spacing:-0.5px;';
       opnlEl.textContent = (opnl >= 0 ? '+' : '') + dollar(opnl);
     }
     const pnlEl = $('crypto-sub-pnl');
     if (pnlEl) {
       pnlEl.className = pcls(pnl);
       pnlEl.style.cssText = 'font-size:22px;font-weight:700;letter-spacing:-0.5px;';
       pnlEl.textContent = (pnl >= 0 ? '+' : '') + dollar(pnl);
     }
     const wrEl = $('crypto-sub-winrate');
     if (wrEl) {
       if (d.win_rate != null) { wrEl.textContent = d.win_rate.toFixed(0) + '%'; wrEl.style.color = '#4ade80'; }
       else { wrEl.textContent = '--'; wrEl.style.color = '#888'; }
     }
     $('crypto-sub-open-dep').textContent = dollar(d.open_deployed || 0);
     $('crypto-sub-open-cnt').textContent = d.open_trades != null ? d.open_trades : '--';
     $('crypto-sub-total-trades').textContent = (d.trade_count || 0) + (d.open_trades || 0);
   }
   ```

6. **Update `renderState()`** (line 1189–1192):
   ```js
   window._moduleData = modules;
   // Parent-level module cards (no longer includes 'crypto' — it's tabbed now)
   ['weather', 'fed', 'geo', 'sports'].forEach(m => {
     if (modules[m]) renderModuleCard(m);
   });
   // Crypto sub-module tabs
   window._cryptoSubData = {
     crypto_15m_dir:  modules.crypto_15m_dir  || {},
     crypto_1h_dir:   modules.crypto_1h_dir   || {},
     crypto_1h_band:  modules.crypto_1h_band  || {},
     crypto_1d:       modules.crypto_1d       || {},
   };
   renderCryptoSubCard();
   ```

7. **Remove `'crypto'` from `MODULE_ID`** (but keep it in `_moduleData` for backward compat if anything references it).

### Risk/Edge cases

1. **Sub-modules with zero trades** will show all `--` / `$0.00`. This is expected — 1H Dir and 1H Band don't have trades yet.

2. **Double-counting:** The backend must accumulate into BOTH the parent `crypto` key AND the sub-module key. The aggregated `crypto` parent is still needed for the account-level P&L calculation in `_build_state()`. Don't remove it — just stop rendering it as a card.

3. **`crypto_1d` alias:** `classify_module()` returns `crypto_1h_dir` for 1D tickers. The tab key sent from the frontend will be `crypto_1d`, so the backend alias is required: `modules_out['crypto_1d'] = modules_out['crypto_1h_dir']`.

4. **Period selector:** The crypto sub-module card should include "Today" and "This Week" options (like the current crypto card does, unlike Weather/Geo/Fed which lack day/week). This is because crypto trades settle frequently.

5. **Existing crypto data consumers:** The `loadCrypto()` function (line 1375) and crypto scan tab are separate from the module card. They are NOT affected by this change — that's the Crypto Market Data section, not the P&L card.

---

## Summary of All Files to Touch

| File | Changes |
|------|---------|
| `logger.py` | Add `sports_odds` classification + `sports` parent module |
| `api.py` → `_build_state()` | Add `sports` + crypto sub-modules to `module_keys`, dual-accumulation for sub-modules, `crypto_1d` alias |
| `api.py` → `/api/pnl` | Same module_keys expansion (if legacy endpoint kept) |
| `index.html` — HTML | Move cards (Weather / Sports / Geo / Fed / Crypto-tabbed), replace Sports card HTML, replace Crypto card HTML |
| `index.html` — CSS | Remove `.sports-table` styles (dead code) |
| `index.html` — JS | Add `sports` to MODULE_ID + modulePeriod + renderState loop; Add `switchCryptoSub()`, `setCryptoSubPeriod()`, `renderCryptoSubCard()`; Remove `refreshSports()` from loadAll; Remove old crypto MODULE_ID entry |
