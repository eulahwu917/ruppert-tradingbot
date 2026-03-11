import sys
sys.stdout.reconfigure(encoding='utf-8')
path = 'dashboard/templates/index.html'
c = open(path, encoding='utf-8').read()

# Fix Open Positions title cell — inline flexbox: [title...] [BOT]
old_pos_td = '''      <td class="l col-title">
        <a href="${url}" target="_blank" style="color:#aaa;text-decoration:none;font-size:11px;white-space:normal;line-height:1.4;">${name}</a>
        <div style="margin-top:2px;">${src}</div>
      </td>'''
new_pos_td = '''      <td class="l col-title" style="max-width:0;">
        <div style="display:flex;align-items:center;gap:6px;min-width:0;">
          <a href="${url}" target="_blank" style="color:#aaa;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;">${name}</a>
          ${src}
        </div>
      </td>'''
if old_pos_td in c:
    c = c.replace(old_pos_td, new_pos_td)
    print("pos td: OK")
else:
    print("pos td: NOT FOUND")

# Fix Trade History title cell — same treatment
old_tr_td = '''      <td class="l col-title">
        <a href="${url}" target="_blank" style="color:#ccc;text-decoration:none;font-size:11px;white-space:normal;line-height:1.4;">${q}</a>
        <div style="margin-top:2px;">${src}</div>
      </td>'''
new_tr_td = '''      <td class="l col-title" style="max-width:0;">
        <div style="display:flex;align-items:center;gap:6px;min-width:0;">
          <a href="${url}" target="_blank" style="color:#ccc;text-decoration:none;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;">${q}</a>
          ${src}
        </div>
      </td>'''
if old_tr_td in c:
    c = c.replace(old_tr_td, new_tr_td)
    print("trade td: OK")
else:
    print("trade td: NOT FOUND")

open(path, 'w', encoding='utf-8').write(c)
print("Done")
