import sys
sys.stdout.reconfigure(encoding='utf-8')
c = open('dashboard/templates/index.html', encoding='utf-8').read()
# Check current tbl CSS
idx = c.find('.tbl {')
print("TBL CSS:", repr(c[idx:idx+400]))
print()
# Check title <a> style
idx2 = c.find('color:#aaa;text-decoration:none')
print("TITLE A:", repr(c[idx2:idx2+120]))
