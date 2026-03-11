import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Table CSS — equal columns, wider title
old_tbl = '.tbl { width: 100%; border-collapse: collapse; font-size: 12px; }'
new_tbl = '''.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.tbl th, .tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tbl .col-title { width: 32%; }
.tbl .col-signal { width: 13%; }
.tbl .col-edge   { width: 8%; }
.tbl .col-sm     { width: 8%; }
.tbl .col-entry  { width: 8%; }
.tbl .col-cur    { width: 8%; }
.tbl .col-cost   { width: 9%; }
.tbl .col-pnl    { width: 14%; }'''
if old_tbl in c:
    c = c.replace(old_tbl, new_tbl)
    print("tbl CSS: OK")
else:
    print("tbl CSS: NOT FOUND")

# 2. Open Positions thead — reorder: Title | Signal vs Mkt | Edge | Qty | Side | Entry | Current | Cost | Open P&L
old_pos_head = '''            <th class="l">Position</th>
            <th>Qty</th><th>Side</th><th>Entry</th><th>Current</th>
            <th>Cost</th><th>Open P&L</th><th>NOAA vs Mkt</th><th>Edge</th>'''
new_pos_head = '''            <th class="l col-title">Position</th>
            <th class="col-signal">Signal vs Mkt</th><th class="col-edge">Edge</th>
            <th class="col-sm">Qty</th><th class="col-sm">Side</th><th class="col-entry">Entry</th>
            <th class="col-cur">Current</th><th class="col-cost">Cost</th><th class="col-pnl">Open P&L</th>'''
if old_pos_head in c:
    c = c.replace(old_pos_head, new_pos_head)
    print("pos thead: OK")
else:
    print("pos thead: NOT FOUND")

# 3. Open Positions row — reorder columns, badge on second line
old_row = """    const src    = (['geo','gaming','manual'].includes(p.source))
                   ? '<span class="b-manual">MANUAL</span>' : '<span class="b-bot">BOT</span>';
    const noaa   = (p.noaa_prob != null && p.market_prob != null)
                   ? Math.round(p.noaa_prob*100)+'% vs '+Math.round(p.market_prob*100)+'%' : '--';
    const edgeV  = (p.edge != null) ? (Math.abs(p.edge)*100).toFixed(0)+'%' : '--';
    const edgeC  = (p.edge && Math.abs(p.edge)>.4) ? '#4ade80' : (p.edge && Math.abs(p.edge)>.2) ? '#fbbf24' : '#888';
    return `<tr>
      <td class="l" style="max-width:220px;">
        <a href="${url}" target="_blank" style="color:#aaa;text-decoration:none;font-size:11px;">${name}</a>${src}
      </td>
      <td>${p.contracts}</td>
      <td>${side}</td>
      <td>${p.entry_price ? p.entry_price+'c' : '--'}</td>
      <td id="cp-${p.ticker}">${cur}</td>
      <td>${dollar(p.total_cost)}</td>
      <td id="opnl-${p.ticker}">${pnlH(p.open_pnl)}<br><span style="font-size:9px;color:#2a2a2a">Pending</span></td>
      <td style="font-size:10px;color:#2a2a2a">${noaa}</td>
      <td style="color:${edgeC};font-weight:700">${edgeV}</td>
    </tr>`;"""
new_row = """    const src    = (['geo','gaming','manual'].includes(p.source))
                   ? '<span class="b-manual">MANUAL</span>' : '<span class="b-bot">BOT</span>';
    const sigVal = (p.noaa_prob != null && p.market_prob != null)
                   ? Math.round(p.noaa_prob*100)+'% vs '+Math.round(p.market_prob*100)+'%' : '--';
    const edgeV  = (p.edge != null) ? (Math.abs(p.edge)*100).toFixed(0)+'%' : '--';
    const edgeC  = (p.edge && Math.abs(p.edge)>.4) ? '#4ade80' : (p.edge && Math.abs(p.edge)>.2) ? '#fbbf24' : '#888';
    return `<tr>
      <td class="l col-title">
        <a href="${url}" target="_blank" style="color:#aaa;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;">${name}</a>
        <div style="margin-top:2px;">${src}</div>
      </td>
      <td class="col-signal" style="font-size:10px;color:#555;">${sigVal}</td>
      <td class="col-edge" style="color:${edgeC};font-weight:700;">${edgeV}</td>
      <td class="col-sm">${p.contracts}</td>
      <td class="col-sm">${side}</td>
      <td class="col-entry">${p.entry_price ? p.entry_price+'c' : '--'}</td>
      <td class="col-cur" id="cp-${p.ticker}">${cur}</td>
      <td class="col-cost">${dollar(p.total_cost)}</td>
      <td class="col-pnl" id="opnl-${p.ticker}">${pnlH(p.open_pnl)}<br><span style="font-size:9px;color:#2a2a2a">Pending</span></td>
    </tr>`;"""
if old_row in c:
    c = c.replace(old_row, new_row)
    print("pos row: OK")
else:
    print("pos row: NOT FOUND")

# 4. Trade History thead — match new column set
old_tr_head = '            <th class="l">Trade</th><th>Qty</th><th>Side</th><th>Entry</th><th>Cost</th><th>P&L</th>'
new_tr_head = '            <th class="l col-title">Trade</th><th class="col-sm">Qty</th><th class="col-sm">Side</th><th class="col-entry">Entry</th><th class="col-cost">Cost</th><th class="col-pnl">P&L</th>'
if old_tr_head in c:
    c = c.replace(old_tr_head, new_tr_head)
    print("trade thead: OK")
else:
    print("trade thead: NOT FOUND")

# 5. Trade History row — badge on second line
old_tr_row = """    return `<tr>
      <td class="l" style="max-width:220px;">
        <a href="${url}" target="_blank" style="color:#ccc;text-decoration:none;font-size:11px;">${q}</a>${src}
      </td>
      <td>${t.contracts||'--'}</td>
      <td>${side}</td>
      <td>${entryP}c</td>
      <td>${dollar(t.size_dollars)}</td>
      <td style="font-weight:700;color:${rpnlC}">${rpnl}</td>
    </tr>`;"""
new_tr_row = """    return `<tr>
      <td class="l col-title">
        <a href="${url}" target="_blank" style="color:#ccc;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;">${q}</a>
        <div style="margin-top:2px;">${src}</div>
      </td>
      <td class="col-sm">${t.contracts||'--'}</td>
      <td class="col-sm">${side}</td>
      <td class="col-entry">${entryP}c</td>
      <td class="col-cost">${dollar(t.size_dollars)}</td>
      <td class="col-pnl" style="font-weight:700;color:${rpnlC}">${rpnl}</td>
    </tr>`;"""
if old_tr_row in c:
    c = c.replace(old_tr_row, new_tr_row)
    print("trade row: OK")
else:
    print("trade row: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
