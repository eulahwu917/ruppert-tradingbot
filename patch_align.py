import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# Right-align numeric columns via colgroup + th/td text-align
old_tbl_css = '.tbl th { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n.tbl td { overflow: hidden; }'
new_tbl_css = '''.tbl th { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tbl td { overflow: hidden; }
.tbl .ra { text-align: right; }
.tbl .ca { text-align: center; }'''
if old_tbl_css in c:
    c = c.replace(old_tbl_css, new_tbl_css)
    print("CSS: OK")
else:
    print("CSS: NOT FOUND")

# Right-align th headers for Signal, Edge, Qty, Entry, Cur, Cost, P&L
old_pos_thead = '''          <thead><tr>
            <th class="l">Position</th>
            <th>Signal</th><th>Edge</th>
            <th>Qty</th><th>Side</th><th>Entry</th>
            <th>Cur</th><th>Cost</th><th>Open P&L</th>
          </tr></thead>'''
new_pos_thead = '''          <thead><tr>
            <th class="l">Position</th>
            <th class="ra">Signal</th><th class="ra">Edge</th>
            <th class="ra">Qty</th><th class="ca">Side</th><th class="ra">Entry</th>
            <th class="ra">Cur</th><th class="ra">Cost</th><th class="ra">Open P&L</th>
          </tr></thead>'''
if old_pos_thead in c:
    c = c.replace(old_pos_thead, new_pos_thead)
    print("pos thead: OK")
else:
    print("pos thead: NOT FOUND")

# Right-align td cells in positions row
c = c.replace(
    '<td class="col-signal" style="font-size:10px;color:#555;">${sigVal}</td>',
    '<td class="col-signal ra" style="font-size:10px;color:#555;">${sigVal}</td>'
)
c = c.replace(
    '<td class="col-edge" style="color:${edgeC};font-weight:700;">${edgeV}</td>',
    '<td class="col-edge ra" style="color:${edgeC};font-weight:700;">${edgeV}</td>'
)
c = c.replace(
    '<td class="col-sm">${p.contracts}</td>',
    '<td class="col-sm ra">${p.contracts}</td>'
)
c = c.replace(
    '<td class="col-entry">${p.entry_price ? p.entry_price+\'c\' : \'--\'}</td>',
    '<td class="col-entry ra">${p.entry_price ? p.entry_price+\'c\' : \'--\'}</td>'
)
c = c.replace(
    '<td class="col-cur" id="cp-${p.ticker}">${cur}</td>',
    '<td class="col-cur ra" id="cp-${p.ticker}">${cur}</td>'
)
c = c.replace(
    '<td class="col-cost">${dollar(p.total_cost)}</td>',
    '<td class="col-cost ra">${dollar(p.total_cost)}</td>'
)
c = c.replace(
    '<td class="col-pnl" id="opnl-${p.ticker}">${pnlH(p.open_pnl)}<br>',
    '<td class="col-pnl ra" id="opnl-${p.ticker}">${pnlH(p.open_pnl)}<br>'
)

# Right-align trade history number columns
old_tr_thead = '          <thead><tr>\n            <th class="l">Trade</th><th>Qty</th><th>Side</th><th>Entry</th><th>Cost</th><th>P&L</th>\n          </tr></thead>'
new_tr_thead = '          <thead><tr>\n            <th class="l">Trade</th><th class="ra">Qty</th><th class="ca">Side</th><th class="ra">Entry</th><th class="ra">Cost</th><th class="ra">P&L</th>\n          </tr></thead>'
if old_tr_thead in c:
    c = c.replace(old_tr_thead, new_tr_thead)
    print("trade thead: OK")
else:
    print("trade thead: NOT FOUND")

c = c.replace(
    '<td class="col-sm">${t.contracts||\'--\'}</td>',
    '<td class="col-sm ra">${t.contracts||\'--\'}</td>'
)
c = c.replace(
    '<td class="col-entry">${entryP}c</td>',
    '<td class="col-entry ra">${entryP}c</td>'
)
c = c.replace(
    '<td class="col-cost">${dollar(t.size_dollars)}</td>',
    '<td class="col-cost ra">${dollar(t.size_dollars)}</td>'
)
c = c.replace(
    '<td class="col-pnl" style="font-weight:700;color:${rpnlC}">${rpnl}</td>',
    '<td class="col-pnl ra" style="font-weight:700;color:${rpnlC}">${rpnl}</td>'
)

print("td aligns: done")
open(path, 'w', encoding='utf-8').write(c)
print("Done")
