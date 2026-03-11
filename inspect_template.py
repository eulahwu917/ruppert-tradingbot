import sys
sys.stdout.reconfigure(encoding='utf-8')
c = open('dashboard/templates/index.html', encoding='utf-8').read()
idx = c.find('async function loadPositions')
print(repr(c[idx+1900:idx+2600]))
