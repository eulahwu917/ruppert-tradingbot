# Crypto Sub-Cards: Individual Module Cards

**Status:** Ready
**File:** `environments/demo/dashboard/templates/index.html`

## Goal

Replace the single full-width Crypto 4-column card with 4 individual module cards (one per crypto sub-module), styled identically to Weather/Sports/Geo/Fed cards.

Layout becomes two 4-col grid rows:
```
Row 1: Weather | Sports Odds | Geo | Fed
Row 2: 15m Dir | 1H Dir     | 1H Band | 1D
```

---

## HTML Changes

### Remove (lines 460-566)
Delete the entire `<!-- Crypto (full-width, 4-column layout) -->` div, including:
- The `grid-column:1/-1` card wrapper
- The shared `crypto-sub-period` select
- The `crypto-4col` flex container with 4 column divs

### Add: New grid row after `module-cards-row` closing `</div>` (line 568)
Insert a second grid row:
```html
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px;" id="crypto-cards-row">
```

Inside it, 4 cards — each cloned from the Weather card structure. Per card:

| Sub-module key | Label | Icon |
|---|---|---|
| `crypto_15m_dir` | 15m Dir | ₿ |
| `crypto_1h_dir` | 1H Dir | ₿ |
| `crypto_1h_band` | 1H Band | ₿ |
| `crypto_1d` | 1D | ₿ |

Each card uses:
- `border-left: 3px solid #a78bfa` (purple, same as current)
- Same padding/structure as Weather card
- Element IDs follow existing MODULE_ID pattern: `{key}-open-pnl`, `{key}-pnl`, `{key}-winrate`, `{key}-open-dep`, `{key}-open-cnt`, `{key}-total-trades`
- Own period `<select>` with `onchange="setModulePeriod('{key}', this.value)"` and `id="{key}-period"`

Example for `crypto_15m_dir` (others identical, swap key/label):
```html
<div class="card" style="border-left:3px solid #a78bfa;">
  <div style="padding:16px;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
      <span style="font-size:18px;">&#x20BF;</span>
      <span style="font-size:13px;font-weight:700;color:#fff;">15m Dir</span>
    </div>
    <!-- Row 1: Open P&L | Closed P&L (period select) | Win Rate -->
    <div style="display:flex;margin-bottom:14px;">
      <div style="flex:1;padding-right:12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Open P&amp;L</div>
        <div class="pnl-neu" id="crypto_15m_dir-open-pnl" style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">--</div>
      </div>
      <div style="flex:1;padding:0 12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;display:flex;align-items:center;justify-content:center;gap:4px;flex-wrap:wrap;">
          Closed P&amp;L
          <select id="crypto_15m_dir-period" onchange="setModulePeriod('crypto_15m_dir',this.value)" style="font-size:8px;background:#0d0d0d;border:1px solid #2a2a2a;border-radius:3px;color:#666;padding:1px 3px;cursor:pointer;outline:none;">
            <option value="month" selected>This Month</option>
            <option value="year">This Year</option>
            <option value="all">All Time</option>
          </select>
        </div>
        <div class="pnl-neu" id="crypto_15m_dir-pnl" style="font-size:22px;font-weight:700;letter-spacing:-0.5px;">--</div>
      </div>
      <div style="flex:1;padding-left:12px;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Win Rate</div>
        <div style="font-size:22px;font-weight:700;color:#888;" id="crypto_15m_dir-winrate">--</div>
      </div>
    </div>
    <!-- Row 2: Open Deployed | Open Trades | Total Trades -->
    <div style="display:flex;border-top:1px solid #1a1a1a;padding-top:12px;">
      <div style="flex:1;padding-right:12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Open Deployed</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="crypto_15m_dir-open-dep">--</div>
      </div>
      <div style="flex:1;padding:0 12px;border-right:1px solid #222;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Open Trades</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="crypto_15m_dir-open-cnt">--</div>
      </div>
      <div style="flex:1;padding-left:12px;text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Total Trades</div>
        <div style="font-size:15px;font-weight:700;color:#888;" id="crypto_15m_dir-total-trades">--</div>
      </div>
    </div>
  </div>
</div>
```

### Mobile responsive (line ~187)
Add `#crypto-cards-row` to the existing 1fr override:
```css
#module-cards-row, #crypto-cards-row { grid-template-columns: 1fr !important; }
```

---

## JS Changes

### MODULE_ID (line 629)
Add crypto sub-modules:
```js
const MODULE_ID = {
  weather: 'weather', fed: 'fed', geo: 'geo', sports: 'sports',
  crypto_15m_dir: 'crypto_15m_dir', crypto_1h_dir: 'crypto_1h_dir',
  crypto_1h_band: 'crypto_1h_band', crypto_1d: 'crypto_1d'
};
```

### _modulePeriod (line 632)
Add entries:
```js
window._modulePeriod = {
  weather:'month', fed:'month', geo:'month', sports:'month',
  crypto_15m_dir:'month', crypto_1h_dir:'month', crypto_1h_band:'month', crypto_1d:'month'
};
```

### Delete (lines 634-736)
Remove all crypto-specific rendering code:
- `window._cryptoSubPeriod`
- `window._cryptoSubData`
- `setCryptoSubPeriod()`
- `renderCrypto4Col()`
- `CRYPTO_SUBS` constant

### Data wiring — initial load (lines 1320-1331)
Replace:
```js
['weather', 'fed', 'geo', 'sports'].forEach(m => {
  if (modules[m]) renderModuleCard(m);
});
window._cryptoSubData = { ... };
renderCrypto4Col();
```
With:
```js
['weather','fed','geo','sports','crypto_15m_dir','crypto_1h_dir','crypto_1h_band','crypto_1d'].forEach(m => {
  if (modules[m]) renderModuleCard(m);
});
```

### Data wiring — polling (lines 1443-1455)
Same pattern: add crypto sub-module keys to the `renderModuleCard` loop, remove `renderCrypto4Col()` call.

---

## CSS Changes

None beyond the mobile breakpoint fix. The existing `.card` class provides all needed styling.

---

## What stays the same

- `renderModuleCard()` is reused as-is (already handles any key via `MODULE_ID[mod] || mod`)
- Win rate color logic (green `#4ade80`) works automatically
- Period selector per-card (each has own dropdown, just like Weather/Sports/Geo/Fed)
- All API data keys (`crypto_15m_dir`, etc.) unchanged
- Crypto scan table/signal/smart-money code untouched
