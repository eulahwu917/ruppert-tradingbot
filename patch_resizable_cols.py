import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# ── 1. Remove col-bar CSS ─────────────────────────────────────────────────────
old_col_css = '''.col-bar { display:flex; align-items:center; gap:4px; padding:8px 12px 6px; flex-wrap:wrap; border-bottom:1px solid #111; }
.col-bar-label { font-size:10px; color:#333; text-transform:uppercase; letter-spacing:.5px; margin-right:2px; }
.col-tog { background:#111; border:1px solid #1e1e1e; color:#444; font-size:10px; padding:2px 8px; border-radius:3px; cursor:pointer; transition:all .15s; }
.col-tog.on { background:#1a2e4a; border-color:#2563eb; color:#93c5fd; }
.col-tog:hover { border-color:#3b82f6; color:#bfdbfe; }'''
if old_col_css in c:
    c = c.replace(old_col_css, '')
    print("col-bar CSS removed: OK")
else:
    print("col-bar CSS: NOT FOUND")

# ── 2. Add resize handle CSS + fixed layout ───────────────────────────────────
old_tbl_css = '.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: auto; }'
new_tbl_css = '''.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.tbl th { position: relative; overflow: hidden; }
.tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tbl td.l { white-space: nowrap; }
.resize-h { position:absolute; right:0; top:0; bottom:0; width:5px; cursor:col-resize; background:transparent; z-index:2; }
.resize-h:hover, .resize-h.active { background:#3b82f6; }'''
if old_tbl_css in c:
    c = c.replace(old_tbl_css, new_tbl_css)
    print("tbl CSS: OK")
else:
    print("tbl CSS: NOT FOUND")

# ── 3. Remove col-bar HTML div ────────────────────────────────────────────────
old_col_bar_html = '''        <div class="col-bar">
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
new_col_bar_html = '        <div class="t-scroll"><table class="tbl" id="pos-tbl">'
if old_col_bar_html in c:
    c = c.replace(old_col_bar_html, new_col_bar_html)
    print("col-bar HTML removed: OK")
else:
    print("col-bar HTML: NOT FOUND")

# ── 4. Add resize handles to thead + default col widths ──────────────────────
old_thead = '''          <thead><tr>
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
new_thead = '''          <thead><tr>
            <th class="l" style="width:260px">Position<div class="resize-h"></div></th>
            <th class="ra" data-col="signal" style="width:100px">Signal<div class="resize-h"></div></th>
            <th class="ra" data-col="edge" style="width:55px">Edge<div class="resize-h"></div></th>
            <th class="ra" data-col="qty" style="width:50px">Qty<div class="resize-h"></div></th>
            <th class="ca" data-col="side" style="width:55px">Side<div class="resize-h"></div></th>
            <th class="ra" data-col="ent" style="width:50px">Ent<div class="resize-h"></div></th>
            <th class="ra" data-col="cur" style="width:50px">Cur<div class="resize-h"></div></th>
            <th class="ra" data-col="cost" style="width:65px">Cost<div class="resize-h"></div></th>
            <th class="ra" style="width:90px">Open P&L<div class="resize-h"></div></th>
          </tr></thead>'''
if old_thead in c:
    c = c.replace(old_thead, new_thead)
    print("thead: OK")
else:
    print("thead: NOT FOUND")

# ── 5. Remove old toggle JS ───────────────────────────────────────────────────
old_toggle_js = '''
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
if old_toggle_js in c:
    c = c.replace(old_toggle_js, '')
    print("old toggle JS removed: OK")
else:
    print("old toggle JS: NOT FOUND")

# Remove applyColPrefs calls
c = c.replace('  applyColPrefs();\n', '')
print("applyColPrefs calls removed: OK")

# ── 6. Add resize JS ──────────────────────────────────────────────────────────
resize_js = '''
// ─── Resizable Columns ────────────────────────────────────────────────────────
(function() {
  let rTh = null, rStartX = 0, rStartW = 0;

  function saveWidths() {
    const tbl = document.getElementById('pos-tbl');
    if (!tbl) return;
    const ws = Array.from(tbl.querySelectorAll('thead th')).map(th => th.offsetWidth);
    localStorage.setItem('ruppert_col_w', JSON.stringify(ws));
  }

  function restoreWidths() {
    try {
      const ws = JSON.parse(localStorage.getItem('ruppert_col_w') || 'null');
      if (!ws) return;
      const tbl = document.getElementById('pos-tbl');
      if (!tbl) return;
      const ths = tbl.querySelectorAll('thead th');
      ths.forEach((th, i) => { if (ws[i] && ws[i] > 20) th.style.width = ws[i] + 'px'; });
    } catch(e) {}
  }

  document.addEventListener('mousedown', function(e) {
    if (!e.target.classList.contains('resize-h')) return;
    rTh = e.target.parentElement;
    rStartX = e.clientX;
    rStartW = rTh.offsetWidth;
    e.target.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', function(e) {
    if (!rTh) return;
    const newW = Math.max(30, rStartW + (e.clientX - rStartX));
    rTh.style.width = newW + 'px';
  });

  document.addEventListener('mouseup', function(e) {
    if (!rTh) return;
    rTh.querySelector('.resize-h').classList.remove('active');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    saveWidths();
    rTh = null;
  });

  // Restore on load + after positions render
  window.restoreColWidths = restoreWidths;
  document.addEventListener('DOMContentLoaded', restoreWidths);
})();
'''

last_script = c.rfind('</script>')
if last_script != -1:
    c = c[:last_script] + resize_js + c[last_script:]
    print("resize JS: OK")
else:
    print("resize JS: NOT FOUND")

# ── 7. Call restoreColWidths after positions load ─────────────────────────────
old_load_end = "  loadLivePrices(positions);\n}"
new_load_end = "  loadLivePrices(positions);\n  if(window.restoreColWidths) restoreColWidths();\n}"
c = c.replace(old_load_end, new_load_end, 1)
print("restore call: OK")

open(path, 'w', encoding='utf-8').write(c)
print("\nAll done.")
