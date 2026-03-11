import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Fix title substring — increase from 50 to 80 chars
old_name = "const name  = (p.title||p.ticker||'').substring(0,50);"
new_name  = "const name  = (p.title||p.ticker||'');"
if old_name in c:
    c = c.replace(old_name, new_name)
    print("title substring: OK")
else:
    print("title substring: NOT FOUND")

# 2. Add column border lines to th and td
old_tbl_css = '.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }'
new_tbl_css = '.tbl { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }'
# Already correct, keep as is

# Add border-right to th and td
old_th_css  = '.tbl th { position: relative; overflow: hidden; }'
new_th_css  = '.tbl th { position: relative; overflow: hidden; border-right: 1px solid #222; }'
if old_th_css in c:
    c = c.replace(old_th_css, new_th_css)
    print("th border: OK")
else:
    print("th border: NOT FOUND")

old_td_css = '.tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }'
new_td_css = '.tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-right: 1px solid #1a1a1a; }'
if old_td_css in c:
    c = c.replace(old_td_css, new_td_css)
    print("td border: OK")
else:
    print("td border: NOT FOUND")

# 3. Make resize handle wider and more prominent
old_rh = '.resize-h { position:absolute; right:0; top:0; bottom:0; width:5px; cursor:col-resize; background:transparent; z-index:2; }'
new_rh = '.resize-h { position:absolute; right:-3px; top:0; bottom:0; width:7px; cursor:col-resize; background:transparent; z-index:3; }'
if old_rh in c:
    c = c.replace(old_rh, new_rh)
    print("resize-h: OK")
else:
    print("resize-h: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
