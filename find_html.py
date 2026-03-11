content = open('dashboard/templates/index.html', encoding='utf-8').read()
# Find all acct-label text
import re
for m in re.finditer(r'acct-label[^>]*>([^<]+)<', content):
    print(repr(m.group(1)))
