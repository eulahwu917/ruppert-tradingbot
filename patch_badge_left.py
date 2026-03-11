import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
api_path = 'dashboard/api.py'
c = open(path, encoding='utf-8').read()

# 1. Open Positions: badge LEFT, no CUR column, fix td layout
old_pos_td = '''      <td class="l col-title" style="max-width:0;">
        <div style="display:flex;align-items:center;gap:6px;min-width:0;">
          <a href="${url}" target="_blank" style="color:#aaa;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;">${name}</a>
          ${src}
        </div>
      </td>'''
new_pos_td = '''      <td class="l col-title" style="max-width:0;">
        <div style="display:flex;align-items:center;gap:6px;min-width:0;">
          ${src}
          <a href="${url}" target="_blank" style="color:#aaa;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1;">${name}</a>
        </div>
      </td>'''
if old_pos_td in c:
    c = c.replace(old_pos_td, new_pos_td)
    print("pos td: OK")
else:
    print("pos td: NOT FOUND")

# 2. Remove CUR column from positions thead
old_head = '''            <th class="ra shrink">Cur</th><th class="ra shrink">Cost</th><th class="ra shrink">Open P&L</th>'''
new_head = '''            <th class="ra shrink">Cost</th><th class="ra shrink">Open P&L</th>'''
if old_head in c:
    c = c.replace(old_head, new_head)
    print("thead cur removed: OK")
else:
    print("thead: NOT FOUND")

# 3. Remove CUR td from positions row
old_cur_td = '''      <td class="ra shrink" id="cp-${p.ticker}">${cur}</td>
      <td class="ra shrink">${dollar(p.total_cost)}</td>'''
new_cur_td = '''      <td class="ra shrink">${dollar(p.total_cost)}</td>'''
if old_cur_td in c:
    c = c.replace(old_cur_td, new_cur_td)
    print("cur td removed: OK")
else:
    print("cur td: NOT FOUND")

# Fix colspans
c = c.replace('colspan="9" class="loading">Loading...', 'colspan="8" class="loading">Loading...')
c = c.replace('colspan="9" class="loading">No open positions today', 'colspan="8" class="loading">No open positions today')

# 4. Trade History: badge LEFT too
old_tr_td = '''      <td class="l col-title" style="max-width:0;">
        <div style="display:flex;align-items:center;gap:6px;min-width:0;">
          <a href="${url}" target="_blank" style="color:#ccc;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;">${q}</a>
          ${src}
        </div>
      </td>'''
new_tr_td = '''      <td class="l col-title" style="max-width:0;">
        <div style="display:flex;align-items:center;gap:6px;min-width:0;">
          ${src}
          <a href="${url}" target="_blank" style="color:#ccc;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1;">${q}</a>
        </div>
      </td>'''
if old_tr_td in c:
    c = c.replace(old_tr_td, new_tr_td)
    print("trade td: OK")
else:
    print("trade td: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)

# 5. Remove cur from loadLivePrices in JS (cp- element no longer exists)
# It'll just silently fail getElementById, no harm. But clean it up anyway.
print("Done")
