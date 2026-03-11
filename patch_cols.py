import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

old = '''.tbl .col-title { width: 32%; }
.tbl .col-signal { width: 13%; }
.tbl .col-edge   { width: 8%; }
.tbl .col-sm     { width: 8%; }
.tbl .col-entry  { width: 8%; }
.tbl .col-cur    { width: 8%; }
.tbl .col-cost   { width: 9%; }
.tbl .col-pnl    { width: 14%; }'''

new = '''.tbl .col-title { width: 36%; }
.tbl .col-signal { width: 11%; }
.tbl .col-edge   { width: 7%; }
.tbl .col-sm     { width: 6%; }
.tbl .col-entry  { width: 6%; }
.tbl .col-cur    { width: 6%; }
.tbl .col-cost   { width: 7%; }
.tbl .col-pnl    { width: 15%; }'''

if old in c:
    c = c.replace(old, new)
    print("cols: OK")
else:
    print("NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
