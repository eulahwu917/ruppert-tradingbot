import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Shorten column headers to prevent truncation
c = c.replace('<th>Signal vs Mkt</th>', '<th>Signal</th>')
c = c.replace('<th>Current</th>', '<th>Cur</th>')
c = c.replace('<th>Entry</th><th>Current</th>', '<th>Entry</th><th>Cur</th>')
print("headers: OK")

# 2. Allow title to wrap (remove white-space: nowrap from title <a> in positions)
old_a = 'style="color:#aaa;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;"'
new_a = 'style="color:#aaa;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;"'
count = c.count(old_a)
c = c.replace(old_a, new_a)
print(f"title wrap: {count} replaced")

# Also fix trade history title <a>
old_a2 = 'style="color:#ccc;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;"'
new_a2 = 'style="color:#ccc;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;"'
count2 = c.count(old_a2)
c = c.replace(old_a2, new_a2)
print(f"trade title wrap: {count2} replaced")

# 3. Fix weather table encoding — replace â€" with proper dash
c = c.replace('â€"', '--')
c = c.replace('\u2014', '--')  # em dash
print("encoding: OK")

# 4. Remove white-space: nowrap from global tbl rule so content can wrap in title col
old_tbl_td = '.tbl th, .tbl td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }'
new_tbl_td = '.tbl th { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n.tbl td { overflow: hidden; }'
if old_tbl_td in c:
    c = c.replace(old_tbl_td, new_tbl_td)
    print("tbl td CSS: OK")
else:
    print("tbl td CSS: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
