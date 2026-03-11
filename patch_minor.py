import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Fix "Entry" header -> "Ent" to avoid truncation in narrow column
c = c.replace('<th class="ra">Entry</th>\n            <th class="ra">Cur</th>', '<th class="ra">Ent</th>\n            <th class="ra">Cur</th>')
c = c.replace('<th class="ra">Entry</th><th class="ra">Cost</th>', '<th class="ra">Ent</th><th class="ra">Cost</th>')
print("header rename: done")

# 2. Fix title cell — make sure it allows wrapping with max 2 lines
# Find the current title <a> style and ensure it wraps
old_a = 'style="color:#aaa;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;"'
new_a = 'style="color:#aaa;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;"'
count = c.count(old_a)
c = c.replace(old_a, new_a)
print(f"title wrap (pos): {count} replaced")

old_a2 = 'style="color:#ccc;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;"'
new_a2 = 'style="color:#ccc;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;"'
count2 = c.count(old_a2)
c = c.replace(old_a2, new_a2)
print(f"title wrap (trade): {count2} replaced")

# 3. Also remove overflow:hidden from the td itself so the 2-line wrap shows fully
c = c.replace('.tbl td { overflow: hidden; }', '.tbl td { }')
print("td overflow: removed")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
