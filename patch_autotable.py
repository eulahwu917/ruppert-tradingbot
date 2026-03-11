import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Switch table CSS: auto layout, shrink cols
old_tbl = '''.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.tbl th { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tbl td { }
.tbl .ra { text-align: right; }
.tbl .ca { text-align: center; }'''

new_tbl = '''.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: auto; }
.tbl th { white-space: nowrap; }
.tbl td { }
.tbl .shrink { width: 1%; white-space: nowrap; }
.tbl .ra { text-align: right; }
.tbl .ca { text-align: center; }'''

if old_tbl in c:
    c = c.replace(old_tbl, new_tbl)
    print("tbl CSS: OK")
else:
    print("tbl CSS: NOT FOUND")

# 2. Remove colgroup from positions table (not needed with auto layout)
old_pos_cg = '''          <colgroup>
            <col style="width:41%"><col style="width:11%"><col style="width:7%">
            <col style="width:6%"><col style="width:6%"><col style="width:6%">
            <col style="width:6%"><col style="width:7%"><col style="width:10%">
          </colgroup>
          <thead>'''
new_pos_cg = '          <thead>'
if old_pos_cg in c:
    c = c.replace(old_pos_cg, new_pos_cg)
    print("pos colgroup removed: OK")
else:
    print("pos colgroup: NOT FOUND")

# 3. Remove colgroup from trade table
old_tr_cg = '''          <colgroup>
            <col style="width:51%"><col style="width:8%"><col style="width:8%">
            <col style="width:8%"><col style="width:10%"><col style="width:15%">
          </colgroup>
          <thead>'''
new_tr_cg = '          <thead>'
if old_tr_cg in c:
    c = c.replace(old_tr_cg, new_tr_cg)
    print("trade colgroup removed: OK")
else:
    print("trade colgroup: NOT FOUND")

# 4. Add .shrink to all non-title th and td in positions table
# Header
old_pos_head = '''          <thead><tr>
            <th class="l">Position</th>
            <th class="ra">Signal</th><th class="ra">Edge</th>
            <th class="ra">Qty</th><th class="ca">Side</th><th class="ra">Ent</th>
            <th class="ra">Cur</th><th class="ra">Cost</th><th class="ra">Open P&L</th>
          </tr></thead>'''
new_pos_head = '''          <thead><tr>
            <th class="l">Position</th>
            <th class="ra shrink">Signal</th><th class="ra shrink">Edge</th>
            <th class="ra shrink">Qty</th><th class="ca shrink">Side</th><th class="ra shrink">Ent</th>
            <th class="ra shrink">Cur</th><th class="ra shrink">Cost</th><th class="ra shrink">Open P&L</th>
          </tr></thead>'''
if old_pos_head in c:
    c = c.replace(old_pos_head, new_pos_head)
    print("pos thead: OK")
else:
    print("pos thead: NOT FOUND")

# Data cells — add shrink to all non-title tds
replacements = [
    ('<td class="col-signal ra"', '<td class="ra shrink"'),
    ('<td class="col-edge ra"', '<td class="ra shrink"'),
    ('<td class="col-sm ra">${p.contracts}', '<td class="ra shrink">${p.contracts}'),
    ('<td class="col-sm">${side}', '<td class="ca shrink">${side}'),
    ('<td class="col-entry ra">', '<td class="ra shrink">'),
    ('<td class="col-cur ra"', '<td class="ra shrink"'),
    ('<td class="col-cost ra">${dollar(p.total_cost)}', '<td class="ra shrink">${dollar(p.total_cost)}'),
    ('<td class="col-pnl ra"', '<td class="ra shrink"'),
    # trade table
    ('<td class="col-sm ra">${t.contracts', '<td class="ra shrink">${t.contracts'),
    ('<td class="col-sm">${side}</td>\n      <td class="col-entry ra"', '<td class="ca shrink">${side}</td>\n      <td class="ra shrink"'),
    ('<td class="col-cost ra">${dollar(t.size_dollars)}', '<td class="ra shrink">${dollar(t.size_dollars)}'),
    ('<td class="col-pnl ra"', '<td class="ra shrink"'),
]
for old, new in replacements:
    if old in c:
        c = c.replace(old, new)

print("td shrink: done")

# 5. Trade history header
old_tr_head = '          <thead><tr>\n            <th class="l">Trade</th><th class="ra">Qty</th><th class="ca">Side</th><th class="ra">Ent</th><th class="ra">Cost</th><th class="ra">P&L</th>\n          </tr></thead>'
new_tr_head = '          <thead><tr>\n            <th class="l">Trade</th><th class="ra shrink">Qty</th><th class="ca shrink">Side</th><th class="ra shrink">Ent</th><th class="ra shrink">Cost</th><th class="ra shrink">P&L</th>\n          </tr></thead>'
if old_tr_head in c:
    c = c.replace(old_tr_head, new_tr_head)
    print("trade thead: OK")
else:
    print("trade thead: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
