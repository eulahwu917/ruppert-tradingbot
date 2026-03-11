import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# ── 1. Add CSS for column toggles ────────────────────────────────────────────
old_css_anchor = '.tbl .shrink { width: 1%; white-space: nowrap; }'
new_css_anchor = '''.tbl .shrink { width: 1%; white-space: nowrap; }
.col-bar { display:flex; align-items:center; gap:4px; padding:8px 12px 6px; flex-wrap:wrap; border-bottom:1px solid #111; }
.col-bar-label { font-size:10px; color:#333; text-transform:uppercase; letter-spacing:.5px; margin-right:2px; }
.col-tog { background:#111; border:1px solid #1e1e1e; color:#444; font-size:10px; padding:2px 8px; border-radius:3px; cursor:pointer; transition:all .15s; }
.col-tog.on { background:#1a2e4a; border-color:#2563eb; color:#93c5fd; }
.col-tog:hover { border-color:#3b82f6; color:#bfdbfe; }'''
if old_css_anchor in c:
    c = c.replace(old_css_anchor, new_css_anchor)
    print("CSS: OK")
else:
    print("CSS: NOT FOUND")

# ── 2. Add column toggle bar above positions table ────────────────────────────
old_pane_open = '      <div class="pane on t-scroll" id="p-pos">\n        <table class="tbl">'
new_pane_open = '''      <div class="pane on" id="p-pos">
        <div class="col-bar">
          <span class="col-bar-label">Cols:</span>
          <button class="col-tog on" data-col="signal" onclick="togCol(\'signal\',this)">Signal</button>
          <button class="col-tog on" data-col="edge" onclick="togCol(\'edge\',this)">Edge</button>
          <button class="col-tog on" data-col="qty" onclick="togCol(\'qty\',this)">Qty</button>
          <button class="col-tog on" data-col="side" onclick="togCol(\'side\',this)">Side</button>
          <button class="col-tog on" data-col="ent" onclick="togCol(\'ent\',this)">Ent</button>
          <button class="col-tog on" data-col="cur" onclick="togCol(\'cur\',this)">Cur</button>
          <button class="col-tog on" data-col="cost" onclick="togCol(\'cost\',this)">Cost</button>
        </div>
        <div class="t-scroll"><table class="tbl">'''
if old_pane_open in c:
    c = c.replace(old_pane_open, new_pane_open)
    print("pane open: OK")
else:
    print("pane open: NOT FOUND")

# Close the extra div before end of pane
old_pane_close = '</tbody>\n        </table>\n      </div>\n      <div class="pane t-scroll" id="p-trades">'
new_pane_close = '</tbody>\n        </table>\n        </div>\n      </div>\n      <div class="pane t-scroll" id="p-trades">'
if old_pane_close in c:
    c = c.replace(old_pane_close, new_pane_close)
    print("pane close: OK")
else:
    print("pane close: NOT FOUND")

# ── 3. Add data-col to thead ─────────────────────────────────────────────────
old_thead = '''          <thead><tr>
            <th class="l">Position</th>
            <th class="ra shrink" style="min-width:80px">Signal</th><th class="ra shrink" style="min-width:45px">Edge</th>
            <th class="ra shrink">Qty</th><th class="ca shrink">Side</th><th class="ra shrink">Ent</th>
            <th class="ra shrink">Cost</th><th class="ra shrink">Open P&L</th>
          </tr></thead>'''
new_thead = '''          <thead><tr>
            <th class="l">Position</th>
            <th class="ra shrink" data-col="signal" style="min-width:80px">Signal</th>
            <th class="ra shrink" data-col="edge" style="min-width:45px">Edge</th>
            <th class="ra shrink" data-col="qty">Qty</th>
            <th class="ca shrink" data-col="side">Side</th>
            <th class="ra shrink" data-col="ent">Ent</th>
            <th class="ra shrink" data-col="cur">Cur</th>
            <th class="ra shrink" data-col="cost">Cost</th>
            <th class="ra shrink">Open P&L</th>
          </tr></thead>'''
if old_thead in c:
    c = c.replace(old_thead, new_thead)
    print("thead: OK")
else:
    print("thead: NOT FOUND")

# ── 4. Fix colspan (8 → 9 now that CUR is back) ──────────────────────────────
c = c.replace('colspan="8" class="loading">Loading...', 'colspan="9" class="loading">Loading...')
c = c.replace('colspan="8" class="loading">No open positions today', 'colspan="9" class="loading">No open positions today')
print("colspan: OK")

# ── 5. Add data-col to JS row template + add CUR cell back ───────────────────
old_row = '''      <td class="ra shrink" style="font-size:10px;color:#555;">${sigVal}</td>
      <td class="ra shrink" style="color:${edgeC};font-weight:700;">${edgeV}</td>
      <td class="ra shrink">${p.contracts}</td>
      <td class="ca shrink">${side}</td>
      <td class="ra shrink">${p.entry_price ? p.entry_price+'c' : '--'}</td>
      <td class="ra shrink">${dollar(p.total_cost)}</td>
      <td class="ra shrink" id="opnl-${p.ticker}">${pnlH(p.open_pnl)}<br><span style="font-size:9px;color:#2a2a2a">Pending</span></td>'''
new_row = '''      <td class="ra shrink" data-col="signal" style="font-size:10px;color:#555;">${sigVal}</td>
      <td class="ra shrink" data-col="edge" style="color:${edgeC};font-weight:700;">${edgeV}</td>
      <td class="ra shrink" data-col="qty">${p.contracts}</td>
      <td class="ca shrink" data-col="side">${side}</td>
      <td class="ra shrink" data-col="ent">${p.entry_price ? p.entry_price+'c' : '--'}</td>
      <td class="ra shrink" data-col="cur" id="cp-${p.ticker}">${cur}</td>
      <td class="ra shrink" data-col="cost">${dollar(p.total_cost)}</td>
      <td class="ra shrink" id="opnl-${p.ticker}">${pnlH(p.open_pnl)}<br><span style="font-size:9px;color:#2a2a2a">Pending</span></td>'''
if old_row in c:
    c = c.replace(old_row, new_row)
    print("row template: OK")
else:
    print("row template: NOT FOUND")

# ── 6. Add column toggle JS before closing </script> ─────────────────────────
toggle_js = '''
// ─── Column Visibility ────────────────────────────────────────────────────────
const COL_DEFS = {signal:1,edge:1,qty:1,side:1,ent:1,cur:1,cost:1};
function loadColPrefs() {
  try { return JSON.parse(localStorage.getItem('ruppert_cols') || '{}'); } catch(e) { return {}; }
}
function applyColPrefs() {
  const prefs = Object.assign({}, COL_DEFS, loadColPrefs());
  Object.keys(COL_DEFS).forEach(col => {
    const vis = !!prefs[col];
    document.querySelectorAll(`[data-col="${col}"]`).forEach(el => {
      el.style.display = vis ? '' : 'none';
    });
    const btn = document.querySelector(`.col-tog[data-col="${col}"]`);
    if (btn) btn.classList.toggle('on', vis);
  });
}
function togCol(col, btn) {
  const prefs = Object.assign({}, COL_DEFS, loadColPrefs());
  prefs[col] = prefs[col] ? 0 : 1;
  localStorage.setItem('ruppert_cols', JSON.stringify(prefs));
  applyColPrefs();
}
'''

# Insert before last </script>
last_script = c.rfind('</script>')
if last_script != -1:
    c = c[:last_script] + toggle_js + c[last_script:]
    print("toggle JS: OK")
else:
    print("toggle JS: NOT FOUND")

# ── 7. Call applyColPrefs after loadPositions renders ────────────────────────
old_async_end = "  loadLivePrices(positions);\n}"
new_async_end = "  loadLivePrices(positions);\n  applyColPrefs();\n}"
# Only replace the first occurrence (inside loadPositions)
c = c.replace(old_async_end, new_async_end, 1)
print("applyColPrefs call: OK")

# ── 8. Also call applyColPrefs on initial page load ──────────────────────────
old_onload = "  refresh();"
new_onload = "  refresh();\n  applyColPrefs();"
c = c.replace(old_onload, new_onload, 1)
print("onload call: OK")

open(path, 'w', encoding='utf-8').write(c)
print("\nAll done.")
