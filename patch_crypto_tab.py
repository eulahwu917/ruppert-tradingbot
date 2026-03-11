"""Patch: Add Crypto tab to Market Scout section"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

path = 'dashboard/templates/index.html'
content = open(path, encoding='utf-8').read()

# 1. Add Crypto tab button
old_tabs = '''      <button class="tab on" onclick="swS('weather',this)">&#x1F327; Weather</button>
      <button class="tab" onclick="swS('bestbets',this)">&#x2B50; Best Bets</button>
      <button class="tab" onclick="swS('geo',this)">&#x1F30D; Geopolitical</button>'''

new_tabs = '''      <button class="tab on" onclick="swS('weather',this)">&#x1F327; Weather</button>
      <button class="tab" onclick="swS('bestbets',this)">&#x2B50; Best Bets</button>
      <button class="tab" onclick="swS('geo',this)">&#x1F30D; Geopolitical</button>
      <button class="tab" onclick="swS('crypto',this)">&#x20BF; Crypto</button>'''

assert old_tabs in content, "Tab buttons not found"
content = content.replace(old_tabs, new_tabs)

# 2. Find where geo pane ends to insert crypto pane after it
# Look for the end of the geo pane
geo_end_marker = '    <!-- End Scout -->'
if geo_end_marker not in content:
    # Try finding the closing of the scout card
    geo_end_marker = '  </div>\n  <!-- scouts end'
    if geo_end_marker not in content:
        # Find the geo pane id and then the next card
        idx = content.find('id="s-geo"')
        # Find closing of that div - look for pattern after geo section
        # Insert before the last </div> of the scout card
        # Find the scout card end by looking for the tab content end
        idx2 = content.find('</div>\n  </div>\n\n  <!-- ', idx)
        geo_end_marker = content[idx2:idx2+30]
        print(f"Using marker: {repr(geo_end_marker)}")

# Find where to insert crypto pane - after geo pane
geo_pane_start = content.find('id="s-geo"')
# Find the pane div containing geo
geo_div_start = content.rfind('<div class="pane"', 0, geo_pane_start)
# Count nesting to find the end of this pane div
depth = 0
pos = geo_div_start
end_pos = geo_div_start
while pos < len(content):
    open_tag = content.find('<div', pos)
    close_tag = content.find('</div>', pos)
    if open_tag == -1 and close_tag == -1:
        break
    if open_tag != -1 and (close_tag == -1 or open_tag < close_tag):
        depth += 1
        pos = open_tag + 4
    else:
        depth -= 1
        pos = close_tag + 6
        if depth == 0:
            end_pos = pos
            break

print(f"Geo pane ends at position {end_pos}")
print(f"Content around end: {repr(content[end_pos-30:end_pos+30])}")

# Insert crypto pane after geo pane
crypto_pane = '''
    <!-- Crypto -->
    <div class="pane" id="s-crypto">
      <div id="crypto-signal-bar" style="display:flex;align-items:center;gap:12px;padding:8px 0 12px;border-bottom:1px solid #1e1e1e;margin-bottom:10px;">
        <span style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.05em;">Smart Money</span>
        <span id="crypto-sm-badge" style="font-size:11px;padding:2px 8px;border-radius:4px;background:#1e1e1e;color:#888;">Loading...</span>
        <span style="font-size:11px;color:#555;">|</span>
        <span style="font-size:11px;color:#888;">BTC</span>
        <span id="crypto-btc-price" style="font-size:13px;font-weight:700;color:#e0e0e0;">--</span>
        <span id="crypto-btc-chg" style="font-size:11px;">--</span>
        <span style="font-size:11px;color:#555;">|</span>
        <span style="font-size:11px;color:#888;">ETH</span>
        <span id="crypto-eth-price" style="font-size:13px;font-weight:700;color:#e0e0e0;">--</span>
        <span id="crypto-eth-chg" style="font-size:11px;">--</span>
      </div>
      <div style="overflow-x:auto;max-height:380px;overflow-y:auto;">
        <table class="tbl wt">
          <thead><tr>
            <th>Market</th>
            <th>Coin</th>
            <th>YES%</th>
            <th>Model%</th>
            <th>Edge</th>
            <th>Signal</th>
            <th>Action</th>
          </tr></thead>
          <tbody id="crypto-b"><tr><td colspan="7" class="loading">Loading crypto markets...</td></tr></tbody>
        </table>
      </div>
      <div style="font-size:10px;color:#444;margin-top:8px;">All crypto trades require David's approval. Smart money signal = aggregate of top 10 Polymarket crypto traders.</div>
    </div>
'''

content = content[:end_pos] + crypto_pane + content[end_pos:]

# 3. Add crypto JS functions before </script>
crypto_js = '''
// ── Crypto Tab ───────────────────────────────────────────────────────────────
async function loadCrypto() {
  const d = await api('/api/crypto/scan');
  const tbody = $('crypto-b');
  if (!d) { tbody.innerHTML = '<tr><td colspan="7" class="loading">Error loading crypto data</td></tr>'; return; }

  // Update signal bar
  const sm = d.smart_money;
  const smBadge = document.getElementById('crypto-sm-badge');
  if (sm) {
    const dir = sm.direction || 'neutral';
    const pct = sm.bull_pct ? Math.round(sm.bull_pct * 100) : '--';
    const colors = {bullish:'#4ade80', bearish:'#f87171', neutral:'#888'};
    smBadge.style.background = dir === 'bullish' ? '#1a2e1a' : dir === 'bearish' ? '#2e1a1a' : '#1e1e1e';
    smBadge.style.color = colors[dir] || '#888';
    smBadge.textContent = dir.toUpperCase() + ' (' + pct + '% bull, ' + sm.traders_sampled + ' traders)';
  }

  // BTC/ETH prices
  if (d.btc) {
    document.getElementById('crypto-btc-price').textContent = '$' + Number(d.btc.price).toLocaleString();
    const chgEl = document.getElementById('crypto-btc-chg');
    const chg = d.btc.change_24h_pct;
    chgEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
    chgEl.style.color = chg >= 0 ? '#4ade80' : '#f87171';
  }
  if (d.eth) {
    document.getElementById('crypto-eth-price').textContent = '$' + Number(d.eth.price).toLocaleString();
    const chgEl = document.getElementById('crypto-eth-chg');
    const chg = d.eth.change_24h_pct;
    chgEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
    chgEl.style.color = chg >= 0 ? '#4ade80' : '#f87171';
  }

  // Opportunities table
  const opps = d.opportunities || [];
  if (!opps.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:#555;text-align:center;padding:20px;">No opportunities above threshold right now</td></tr>';
    return;
  }
  tbody.innerHTML = opps.map(o => {
    const edge = o.edge || 0;
    const edgeCls = edge > 0 ? 'edge-pos' : 'edge-neg';
    const edgeTxt = (edge >= 0 ? '+' : '') + (edge * 100).toFixed(0) + '%';
    const coin = o.ticker.includes('ETH') ? 'ETH' : 'BTC';
    const coinColor = coin === 'BTC' ? '#f7931a' : '#627eea';
    const url = 'https://kalshi.com/markets/' + o.ticker.split('-')[0].toLowerCase();
    return `<tr>
      <td><a href="${url}" target="_blank" style="color:#818cf8;text-decoration:none;">${o.title || o.ticker}</a></td>
      <td><span style="color:${coinColor};font-weight:700;font-size:11px;">${coin}</span></td>
      <td style="text-align:right;">${Math.round((o.market_prob||0)*100)}%</td>
      <td style="text-align:right;">${Math.round((o.model_prob||0)*100)}%</td>
      <td style="text-align:right;"><span class="${edgeCls}">${edgeTxt}</span></td>
      <td style="text-align:center;">${o.direction || '--'}</td>
      <td style="text-align:center;"><button style="background:#1e1e1e;border:1px solid #333;color:#e0e0e0;padding:2px 8px;border-radius:3px;font-size:10px;cursor:pointer;" onclick="alert('Feature coming soon — manual approval flow')">Review</button></td>
    </tr>`;
  }).join('');
}
'''

# Insert before </script>
script_end = content.rfind('</script>')
content = content[:script_end] + crypto_js + '\n' + content[script_end:]

# 4. Hook loadCrypto into swS and loadScouts
# Add to swS function to call loadCrypto when switching to crypto tab
old_sws = "function swS(id,btn){"
if old_sws in content:
    idx_sws = content.find(old_sws)
    end_sws = content.find('\n}', idx_sws) + 2
    sws_func = content[idx_sws:end_sws]
    # Add crypto load call
    new_sws = sws_func.replace(
        "function swS(id,btn){",
        "function swS(id,btn){if(id==='crypto'){loadCrypto();}"
    )
    content = content[:idx_sws] + new_sws + content[end_sws:]

# 5. Add /api/crypto/scan placeholder endpoint note in html comment
# (actual endpoint will be wired in once crypto_scanner is ready)

open(path, 'w', encoding='utf-8').write(content)
print("Crypto tab patched successfully")
print(f"File size: {len(content)} bytes")
