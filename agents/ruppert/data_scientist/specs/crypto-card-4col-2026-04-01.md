# SPEC: Crypto Card — Tabs to 4-Column Layout

**Date:** 2026-04-01
**Author:** Data Scientist
**Scope:** `environments/demo/dashboard/templates/index.html` (HTML + JS only)

---

## Current State

The Crypto card (line ~460) is a full-width card with 4 tabs (`15m Dir | 1H Dir | 1H Band | 1D`). Only one sub-module is visible at a time. Switching tabs calls `switchCryptoSub()` which sets `window._activeCryptoSub` and re-renders a single shared metrics panel.

## Target State

Remove tabs. Show all 4 sub-modules simultaneously as 4 equal columns in one card.

---

## HTML Changes (lines 460–509)

**Remove:** The `<div class="tabs" id="crypto-sub-tabs">` block (lines 462–467).

**Replace** the single `<div id="crypto-sub-body">` with a 4-column flex container. Each column is a self-contained metrics block with its own IDs (suffixed by sub-module key):

```html
<!-- Crypto (full-width, 4-column layout) -->
<div class="card" style="border-left:3px solid #a78bfa;grid-column:1/-1;">
  <div class="card-head">
    <div class="sec"><div class="dot dot-b"></div> Crypto</div>
  </div>
  <div style="display:flex;gap:0;padding:16px;" id="crypto-4col">
    <!-- Repeat this block 4x, once per sub-module key -->
    <!-- Keys: crypto_15m_dir, crypto_1h_dir, crypto_1h_band, crypto_1d -->
    <!-- Labels: 15m Dir, 1H Dir, 1H Band, 1D -->
    <div style="flex:1;padding:0 12px;border-right:1px solid #222;" id="col-crypto_15m_dir">
      <div style="font-size:11px;font-weight:700;color:#a78bfa;text-align:center;margin-bottom:10px;">15m Dir</div>
      <div style="text-align:center;margin-bottom:8px;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Open P&L</div>
        <div class="pnl-neu" id="csub-crypto_15m_dir-open-pnl" style="font-size:18px;font-weight:700;">--</div>
      </div>
      <div style="text-align:center;margin-bottom:8px;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Closed P&L</div>
        <div class="pnl-neu" id="csub-crypto_15m_dir-pnl" style="font-size:18px;font-weight:700;">--</div>
      </div>
      <div style="text-align:center;margin-bottom:8px;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:4px;">Win Rate</div>
        <div style="font-size:18px;font-weight:700;color:#888;" id="csub-crypto_15m_dir-winrate">--</div>
      </div>
      <div style="text-align:center;margin-bottom:8px;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Open Dep</div>
        <div style="font-size:13px;font-weight:700;color:#888;" id="csub-crypto_15m_dir-open-dep">--</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:9px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:3px;">Trades</div>
        <div style="font-size:13px;font-weight:700;color:#888;" id="csub-crypto_15m_dir-total-trades">--</div>
      </div>
    </div>
    <!-- ... repeat for crypto_1h_dir, crypto_1h_band, crypto_1d -->
    <!-- Last column: remove border-right -->
  </div>
</div>
```

Each column stacks metrics vertically. Font sizes reduced slightly (22px -> 18px for main, 15px -> 13px for secondary) to fit 4 columns comfortably.

---

## JS Changes

### Remove (lines 577–693)

- `window._activeCryptoSub` — no longer needed (no active tab)
- `switchCryptoSub()` — delete entirely
- `setCryptoSubPeriod()` — delete (see period selector note below)
- `renderCryptoSubCard()` — replace with `renderCrypto4Col()`

### Add: `renderCrypto4Col()`

```js
const CRYPTO_SUBS = ['crypto_15m_dir','crypto_1h_dir','crypto_1h_band','crypto_1d'];

function renderCrypto4Col() {
  const period = window._cryptoSubPeriod || 'month';
  CRYPTO_SUBS.forEach(sub => {
    const d = window._cryptoSubData[sub];
    const el = id => $('csub-' + sub + '-' + id);
    if (!d || !Object.keys(d).length) {
      ['open-pnl','pnl','winrate','open-dep','total-trades'].forEach(k => {
        const e = el(k); if(e) e.textContent = '--';
      });
      return;
    }
    const pnl = period === 'day' ? (d.closed_pnl_day ?? 0)
              : period === 'week' ? (d.closed_pnl_week ?? 0)
              : period === 'month' ? (d.closed_pnl_month ?? 0)
              : period === 'year' ? (d.closed_pnl_year ?? 0)
              : d.closed_pnl;

    const opnlEl = el('open-pnl');
    if (opnlEl) { const v = d.open_pnl || 0; opnlEl.className = pcls(v); opnlEl.style.cssText='font-size:18px;font-weight:700;'; opnlEl.textContent = (v>=0?'+':'') + dollar(v); }

    const pnlEl = el('pnl');
    if (pnlEl) { pnlEl.className = pcls(pnl); pnlEl.style.cssText='font-size:18px;font-weight:700;'; pnlEl.textContent = (pnl>=0?'+':'') + dollar(pnl); }

    const wrEl = el('winrate');
    if (wrEl) { if(d.win_rate!=null){ wrEl.textContent=d.win_rate.toFixed(0)+'%'; wrEl.style.color='#4ade80'; } else { wrEl.textContent='--'; wrEl.style.color='#888'; } }

    const depEl = el('open-dep');
    if (depEl) depEl.textContent = dollar(d.open_deployed || 0);

    const ttEl = el('total-trades');
    if (ttEl) ttEl.textContent = (d.trade_count || 0) + (d.open_trades || 0);
  });
}
```

### Update call sites (2 places)

1. **Initial load** (line ~1288): `renderCryptoSubCard()` -> `renderCrypto4Col()`
2. **Live poll** (line ~1412): `renderCryptoSubCard()` -> `renderCrypto4Col()`

---

## Period Selector

**Recommendation: One shared selector**, placed in the card header next to "Crypto". Rationale:
- 4 individual dropdowns would clutter narrow columns
- Users almost always want the same period across all sub-modules
- Keep `window._cryptoSubPeriod` and `setCryptoSubPeriod()` (renamed to trigger `renderCrypto4Col()`)

Place it in the `<div class="card-head">`:
```html
<div class="card-head">
  <div class="sec"><div class="dot dot-b"></div> Crypto</div>
  <select id="crypto-sub-period" onchange="setCryptoSubPeriod(this.value)" style="...">
    <option value="day">Today</option>
    <option value="week">This Week</option>
    <option value="month" selected>This Month</option>
    <option value="year">This Year</option>
    <option value="all">All Time</option>
  </select>
</div>
```

---

## Layout Concerns

- **Max width 1920px** (`.wrap`): 4 columns at ~25% each = ~450px per column. Plenty of space for dollar amounts and percentages.
- **No horizontal scroll risk**: Metrics are short text (e.g., `+$1,234.56`, `67%`).
- **No responsive breakpoint needed**: Dashboard is desktop-only (1920px max-width, no mobile usage).
- **Removed "Open Trades" row** from per-column display — merged into "Trades" showing total. This keeps columns compact. If David wants both, add back as a 6th row; still fits.

---

## Files Changed

| File | Change |
|------|--------|
| `environments/demo/dashboard/templates/index.html` | HTML: replace tabs+body with 4-col flex. JS: replace `switchCryptoSub`/`renderCryptoSubCard` with `renderCrypto4Col`, update 2 call sites. |

No backend, API, or Python changes needed.
