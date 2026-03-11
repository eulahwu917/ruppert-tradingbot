import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
html = Path('dashboard/templates/index.html').read_text(encoding='utf-8')
# Check acct-main font size in CSS
idx = html.find('.acct-main')
print(repr(html[idx:idx+80]))
