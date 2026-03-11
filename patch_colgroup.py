import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Remove CSS class widths — replace with just base tbl style
old_tbl_css = '''.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.tbl th, .tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tbl .col-title { width: 36%; }
.tbl .col-signal { width: 11%; }
.tbl .col-edge   { width: 7%; }
.tbl .col-sm     { width: 6%; }
.tbl .col-entry  { width: 6%; }
.tbl .col-cur    { width: 6%; }
.tbl .col-cost   { width: 7%; }
.tbl .col-pnl    { width: 15%; }'''

new_tbl_css = '''.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.tbl th, .tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }'''

if old_tbl_css in c:
    c = c.replace(old_tbl_css, new_tbl_css)
    print("CSS: OK")
else:
    print("CSS: NOT FOUND")

# 2. Add colgroup to Open Positions table (9 cols: Title|Signal|Edge|Qty|Side|Entry|Cur|Cost|P&L)
# Widths: 36, 11, 7, 6, 6, 6, 6, 7, 15 = 100%
old_pos_table = '''        <table class="tbl">
          <thead><tr>
            <th class="l col-title">Position</th>
            <th class="col-signal">Signal vs Mkt</th><th class="col-edge">Edge</th>
            <th class="col-sm">Qty</th><th class="col-sm">Side</th><th class="col-entry">Entry</th>
            <th class="col-cur">Current</th><th class="col-cost">Cost</th><th class="col-pnl">Open P&L</th>
          </tr></thead>
          <tbody id="pos-b"><tr><td colspan="9" class="loading">Loading...</td></tr></tbody>
        </table>'''

new_pos_table = '''        <table class="tbl">
          <colgroup>
            <col style="width:36%"><col style="width:11%"><col style="width:7%">
            <col style="width:6%"><col style="width:6%"><col style="width:6%">
            <col style="width:6%"><col style="width:7%"><col style="width:15%">
          </colgroup>
          <thead><tr>
            <th class="l">Position</th>
            <th>Signal vs Mkt</th><th>Edge</th>
            <th>Qty</th><th>Side</th><th>Entry</th>
            <th>Current</th><th>Cost</th><th>Open P&L</th>
          </tr></thead>
          <tbody id="pos-b"><tr><td colspan="9" class="loading">Loading...</td></tr></tbody>
        </table>'''

if old_pos_table in c:
    c = c.replace(old_pos_table, new_pos_table)
    print("pos colgroup: OK")
else:
    print("pos colgroup: NOT FOUND")

# 3. Add colgroup to Trade History table (6 cols: Title|Qty|Side|Entry|Cost|P&L)
# Widths: 46, 8, 8, 8, 10, 20 = 100%
old_tr_table = '''        <table class="tbl">
          <thead><tr>
            <th class="l col-title">Trade</th><th class="col-sm">Qty</th><th class="col-sm">Side</th><th class="col-entry">Entry</th><th class="col-cost">Cost</th><th class="col-pnl">P&L</th>
          </tr></thead>
          <tbody id="tr-b"><tr><td colspan="6" class="loading">Loading...</td></tr></tbody>
        </table>'''

new_tr_table = '''        <table class="tbl">
          <colgroup>
            <col style="width:46%"><col style="width:8%"><col style="width:8%">
            <col style="width:8%"><col style="width:10%"><col style="width:20%">
          </colgroup>
          <thead><tr>
            <th class="l">Trade</th><th>Qty</th><th>Side</th><th>Entry</th><th>Cost</th><th>P&L</th>
          </tr></thead>
          <tbody id="tr-b"><tr><td colspan="6" class="loading">Loading...</td></tr></tbody>
        </table>'''

if old_tr_table in c:
    c = c.replace(old_tr_table, new_tr_table)
    print("trade colgroup: OK")
else:
    print("trade colgroup: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
