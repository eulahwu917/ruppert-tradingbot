import sys
sys.stdout.reconfigure(encoding='utf-8')
c = open('dashboard/templates/index.html', encoding='utf-8').read()
for needle in ['b-yes', 'b-no', 'b-sim']:
    idx = c.find(needle)
    if idx != -1:
        print(needle, '@', idx, repr(c[max(0,idx-30):idx+60]))
    else:
        print(needle, 'NOT FOUND')
