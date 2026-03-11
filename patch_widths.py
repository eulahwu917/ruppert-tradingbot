import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Stretch page to fill full screen width
old_wrap = '.wrap { max-width: 1440px; margin: 0 auto; padding: 16px 20px; }'
new_wrap = '.wrap { max-width: 1920px; margin: 0 auto; padding: 16px 32px; }'
if old_wrap in c:
    c = c.replace(old_wrap, new_wrap)
    print("wrap: OK")
else:
    print("wrap: NOT FOUND")

# 2. Shrink P&L col, grow title col in positions table
# Current: 36, 11, 7, 6, 6, 6, 6, 7, 15 = 100
# New:     41, 11, 7, 6, 6, 6, 6, 7, 10 = 100
old_colgroup = '''          <colgroup>
            <col style="width:36%"><col style="width:11%"><col style="width:7%">
            <col style="width:6%"><col style="width:6%"><col style="width:6%">
            <col style="width:6%"><col style="width:7%"><col style="width:15%">
          </colgroup>'''
new_colgroup = '''          <colgroup>
            <col style="width:41%"><col style="width:11%"><col style="width:7%">
            <col style="width:6%"><col style="width:6%"><col style="width:6%">
            <col style="width:6%"><col style="width:7%"><col style="width:10%">
          </colgroup>'''
if old_colgroup in c:
    c = c.replace(old_colgroup, new_colgroup)
    print("pos colgroup: OK")
else:
    print("pos colgroup: NOT FOUND")

# 3. Trade history: same treatment — title 51%, P&L 14%
# Current: 46, 8, 8, 8, 10, 20
# New:     51, 8, 8, 8, 10, 15
old_tr_colgroup = '''          <colgroup>
            <col style="width:46%"><col style="width:8%"><col style="width:8%">
            <col style="width:8%"><col style="width:10%"><col style="width:20%">
          </colgroup>'''
new_tr_colgroup = '''          <colgroup>
            <col style="width:51%"><col style="width:8%"><col style="width:8%">
            <col style="width:8%"><col style="width:10%"><col style="width:15%">
          </colgroup>'''
if old_tr_colgroup in c:
    c = c.replace(old_tr_colgroup, new_tr_colgroup)
    print("trade colgroup: OK")
else:
    print("trade colgroup: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
