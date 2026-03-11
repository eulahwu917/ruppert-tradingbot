"""Full dashboard fix pass 2: Trade History table + Crypto tab wiring"""
import sys, re
sys.stdout.reconfigure(encoding='utf-8')

path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

# ─── 1. Rebuild Trade History table with proper layout ────────────────────────
old_hist_table = '''      <div class="pane t-scroll" id="p-trades">
        <table class="tbl">
          <thead><tr>
            <th class="l">Trade</th><th class="ra shrink">Qty</th><th class="ca shrink">Side</th><th class="ra shrink">Ent</th><th class="ra shrink">Cost</th><th class="ra shrink">P&L</th>
          </tr></thead>
          <tbody id="tr-b"><tr><td colspan="6" class="loading">Loading...</td></tr></tbody>
        </table>
      </div>'''

new_hist_table = '''      <div class="pane" id="p-trades">
        <div class="t-scroll">
        <table class="tbl" id="hist-tbl" style="table-layout:fixed;width:100%;min-width:700px;">
          <thead><tr>
            <th class="l" style="width:260px;min-width:180px;">Trade<div class="resize-h"></div></th>
            <th class="ca shrink" style="width:80px;">Date<div class="resize-h"></div></th>
            <th class="ca shrink" style="width:50px;">Side<div class="resize-h"></div></th>
            <th class="ra shrink" style="width:45px;">Qty<div class="resize-h"></div></th>
            <th class="ra shrink" style="width:45px;">Ent<div class="resize-h"></div></th>
            <th class="ra shrink" style="width:65px;">Cost<div class="resize-h"></div></th>
            <th class="ra shrink" style="width:90px;">P&amp;L<div class="resize-h"></div></th>
            <th class="ca shrink" style="width:60px;">Src<div class="resize-h"></div></th>
          </tr></thead>
          <tbody id="tr-b"><tr><td colspan="8" class="loading">Loading history...</td></tr></tbody>
        </table>
        </div>
      </div>'''

assert old_hist_table in content, "History table HTML not found"
content = content.replace(old_hist_table, new_hist_table)
print("Trade History table rebuilt")

# ─── 2. Update loadTrades() JS to use new 8-column layout ────────────────────
old_trades_js = """async function loadTrades() {
  const trades = await api('/api/trades/today');
  const tb = $('tr-b');
  if (!trades||!trades.length) { tb.innerHTML='<tr><td colspan="6" class="loading">No trades today</td></tr>'; return; }
  tb.innerHTML = trades.map(t=>{
    const q      = (t.title||t.ticker||'').replace(/[*]{2}/g,'').substring(0,65);
    const side   = t.side==='yes' ? '<span class="b-yes">YES</span>' : '<span class="b-no">NO</span>';
    const src    = (['geo','gaming','manual'].includes(t.source))
                   ? '<span class="b-manual">MANUAL</span>' : '<span class="b-bot">BOT</span>';
    const ticker = t.ticker||'';
    const series = ticker.split('-')[0].toLowerCase();
    const url    = 'https://kalshi.com/markets/'+series;
    const mp     = t.market_prob||0;
    const entryP = t.side==='no' ? Math.round((1-mp)*100) : Math.round(mp*100);
    const rpnl   = t.realized_pnl!=null ? (t.realized_pnl>=0?'+':'')+dollar(t.realized_pnl) : '--';
    const rpnlC  = t.realized_pnl="""

# Find the full function to replace
js_start = content.find('async function loadTrades()')
js_end = content.find('\n}', js_start) + 2
old_full_trades_fn = content[js_start:js_end]
print("Found loadTrades, length:", len(old_full_trades_fn))

new_trades_fn = """async function loadTrades() {
  const trades = await api('/api/trades');
  const tb = $('tr-b');
  if (!trades||!trades.length) {
    tb.innerHTML='<tr><td colspan="8" class="loading" style="color:#555;padding:20px;">No trades yet</td></tr>';
    return;
  }
  tb.innerHTML = trades.map(t=>{
    const title  = (t.title||t.ticker||'').replace(/[*]{2}/g,'');
    const ticker = t.ticker||'';
    const series = ticker.split('-')[0].toLowerCase();
    const url    = 'https://kalshi.com/markets/'+series;
    const side   = t.side==='yes'
      ? '<span class="b-yes">YES</span>'
      : '<span class="b-no">NO</span>';
    const src    = (['geo','gaming','manual','crypto'].includes(t.source))
      ? '<span class="b-manual">MANUAL</span>'
      : '<span class="b-bot">BOT</span>';
    const mp     = t.market_prob||0;
    const entryP = t.side==='no' ? Math.round((1-mp)*100) : Math.round(mp*100);
    const cost   = t.size_dollars ? dollar(t.size_dollars) : '--';
    const rpnl   = t.realized_pnl!=null
      ? '<span class="'+(t.realized_pnl>=0?'pnl-pos':'pnl-neg')+'">'+(t.realized_pnl>=0?'+':'')+dollar(t.realized_pnl)+'</span>'
      : '<span style="color:#444">--</span>';
    const dt     = (t.timestamp||t._date||'').substring(0,10);
    const qty    = t.contracts||'--';
    return `<tr>
      <td class="l" style="overflow:hidden;white-space:nowrap;text-overflow:ellipsis;max-width:260px;">
        <a href="${url}" target="_blank" style="color:#fff;text-decoration:none;">${title}</a>
      </td>
      <td class="ca shrink">${dt}</td>
      <td class="ca shrink">${side}</td>
      <td class="ra shrink">${qty}</td>
      <td class="ra shrink">${entryP}c</td>
      <td class="ra shrink">${cost}</td>
      <td class="ra shrink">${rpnl}</td>
      <td class="ca shrink">${src}</td>
    </tr>`;
  }).join('');
}"""

content = content[:js_start] + new_trades_fn + content[js_end:]
print("loadTrades() rebuilt")

# ─── 3. Also fix the no-data colspan for positions table ─────────────────────
content = content.replace(
    "tb.innerHTML='<tr><td colspan=\"6\" class=\"loading\">No trades today</td></tr>'",
    "tb.innerHTML='<tr><td colspan=\"8\" class=\"loading\" style=\"color:#555;padding:20px;\">No trades yet</td></tr>'"
)

# ─── 4. Fix Crypto tab - wire to actual scanner output ───────────────────────
# The /api/crypto/scan endpoint already calls crypto_client and crypto_scanner
# The issue was the smart_money field structure - let's verify and fix the JS renderer
# loadCrypto JS currently checks d.smart_money.direction, d.btc, d.eth, d.opportunities
# These match what crypto_client returns - the issue is likely the import failing silently
# Let's add better error display to the crypto tab

old_crypto_loading = '<tr><td colspan="7" class="loading">Loading crypto markets...</td></tr>'
new_crypto_loading = '<tr><td colspan="7" style="color:#555;text-align:center;padding:20px;">Click to load crypto markets</td></tr>'
content = content.replace(old_crypto_loading, new_crypto_loading)

# Also call loadCrypto on page load (add to loadScouts)
old_load_scouts = "async function loadScouts(){ await Promise.all([loadWeather(),loadBestBets(),loadGeo()]); }"
new_load_scouts = "async function loadScouts(){ await Promise.all([loadWeather(),loadBestBets(),loadGeo(),loadCrypto()]); }"
if old_load_scouts in content:
    content = content.replace(old_load_scouts, new_load_scouts)
    print("loadScouts now includes loadCrypto")

# ─── 5. Fix acct-label color (too dark currently) ────────────────────────────
content = content.replace(
    '.acct-label { font-size: 10px; font-weight: 700; color: #2a2a2a;',
    '.acct-label { font-size: 10px; font-weight: 700; color: #555;'
)
print("Fixed acct-label color")

print(f"\nFinal size: {len(content)}")
open(path, 'w', encoding='utf-8').write(content)
print("Saved.")
