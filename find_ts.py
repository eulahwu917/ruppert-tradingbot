import sys
sys.stdout.reconfigure(encoding='utf-8')
c = open('dashboard/templates/index.html', encoding='utf-8').read()
needle = "textContent = 'Updated '"
idx = c.find(needle)
print(repr(c[idx-300:idx+100]))
