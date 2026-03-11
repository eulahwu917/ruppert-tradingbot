import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# 1. Title th -> width:100%
old_pos_head = '            <th class="l">Position</th>'
new_pos_head = '            <th class="l" style="width:100%">Position</th>'
if old_pos_head in c:
    c = c.replace(old_pos_head, new_pos_head)
    print("pos th: OK")

old_tr_head = '            <th class="l">Trade</th>'
new_tr_head = '            <th class="l" style="width:100%">Trade</th>'
if old_tr_head in c:
    c = c.replace(old_tr_head, new_tr_head)
    print("trade th: OK")

# 2. Fix title <a>: remove webkit-line-clamp (conflicts with auto width), use simple 2-line wrap
old_a_pos = 'style="color:#aaa;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;"'
new_a_pos = 'style="color:#aaa;text-decoration:none;font-size:11px;white-space:normal;line-height:1.4;"'
c = c.replace(old_a_pos, new_a_pos)
print("pos title a: OK")

old_a_tr = 'style="color:#ccc;text-decoration:none;font-size:11px;white-space:normal;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;"'
new_a_tr = 'style="color:#ccc;text-decoration:none;font-size:11px;white-space:normal;line-height:1.4;"'
c = c.replace(old_a_tr, new_a_tr)
print("trade title a: OK")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
